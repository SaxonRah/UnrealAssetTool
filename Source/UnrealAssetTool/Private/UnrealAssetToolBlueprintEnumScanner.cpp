#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Dom/JsonObject.h"
#include "Engine/UserDefinedEnum.h"
#include "HAL/FileManager.h"
#include "Misc/CommandLine.h"
#include "Misc/CoreDelegates.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace UnrealAssetToolBlueprintEnums
{
static constexpr int32 BlueprintEnumSchemaVersion = 1;

class FJsonlWriter
{
public:
    bool Open(const FString& Filename)
    {
        IFileManager::Get().MakeDirectory(*FPaths::GetPath(Filename), true);
        Archive.Reset(IFileManager::Get().CreateFileWriter(*Filename));
        return Archive.IsValid();
    }

    bool Write(const TSharedRef<FJsonObject>& Object)
    {
        if (!Archive.IsValid())
        {
            return false;
        }
        FString Line;
        const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
            TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);
        if (!FJsonSerializer::Serialize(Object, Writer))
        {
            return false;
        }
        Line.AppendChar(TEXT('\n'));
        FTCHARToUTF8 Utf8(*Line);
        Archive->Serialize((void*)Utf8.Get(), Utf8.Length());
        return !Archive->IsError();
    }

private:
    TUniquePtr<FArchive> Archive;
};

struct FCounts
{
    int64 Enums = 0;
    int64 Entries = 0;
};

static FString NormalizeAbsolutePath(const FString& InPath)
{
    FString Path = FPaths::ConvertRelativePathToFull(InPath);
    FPaths::NormalizeFilename(Path);
    FPaths::CollapseRelativeDirectories(Path);
    return Path;
}

static bool IsInsideDirectory(const FString& File, const FString& Directory)
{
    FString NormalizedFile = NormalizeAbsolutePath(File);
    FString NormalizedDirectory = NormalizeAbsolutePath(Directory);
    if (!NormalizedDirectory.EndsWith(TEXT("/")))
    {
        NormalizedDirectory.AppendChar(TEXT('/'));
    }
    return NormalizedFile.StartsWith(NormalizedDirectory, ESearchCase::IgnoreCase);
}

static bool SaveManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), BlueprintEnumSchemaVersion);
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolBlueprintEnums"));
    Root->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);

    TSharedRef<FJsonObject> CountsJson = MakeShared<FJsonObject>();
    CountsJson->SetNumberField(TEXT("blueprint_enums"), Counts.Enums);
    CountsJson->SetNumberField(TEXT("blueprint_enum_entries"), Counts.Entries);
    Root->SetObjectField(TEXT("counts"), CountsJson);

    TArray<TSharedPtr<FJsonValue>> Files;
    Files.Add(MakeShared<FJsonValueString>(TEXT("blueprint_enums.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("blueprint_enum_entries.jsonl")));
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer))
    {
        return false;
    }
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("blueprint_enum_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunBlueprintEnumScan(FString& OutError)
{
    FString OutputDir;
    FParse::Value(FCommandLine::Get(), TEXT("Output="), OutputDir);
    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    if (OutputDir.IsEmpty())
    {
        OutputDir = FPaths::Combine(ProjectDir, TEXT(".uatool"));
    }
    else if (FPaths::IsRelative(OutputDir))
    {
        OutputDir = FPaths::Combine(ProjectDir, OutputDir);
    }
    OutputDir = NormalizeAbsolutePath(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    FJsonlWriter EnumsWriter;
    FJsonlWriter EntriesWriter;
    FCounts Counts;
    if (!EnumsWriter.Open(FPaths::Combine(OutputDir, TEXT("blueprint_enums.jsonl"))) ||
        !EntriesWriter.Open(FPaths::Combine(OutputDir, TEXT("blueprint_enum_entries.jsonl"))))
    {
        OutError = TEXT("could not create Blueprint enum JSONL output files");
        SaveManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.SearchAllAssets(true);

    TArray<FAssetData> Assets;
    Registry.GetAllAssets(Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString();
    });

    for (const FAssetData& Asset : Assets)
    {
        if (Asset.AssetClassPath.ToString() != TEXT("/Script/Engine.UserDefinedEnum"))
        {
            continue;
        }

        FString PackageFilename;
        if (!FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &PackageFilename, false) ||
            !IsInsideDirectory(PackageFilename, ProjectDir))
        {
            continue;
        }

        UUserDefinedEnum* Enum = Cast<UUserDefinedEnum>(Asset.GetAsset());
        if (!Enum)
        {
            continue;
        }

        const FString EnumPath = Asset.GetSoftObjectPath().ToString();
        const int32 EntryCount = Enum->NumEnums();
        TSharedRef<FJsonObject> EnumRow = MakeShared<FJsonObject>();
        EnumRow->SetStringField(TEXT("enum_path"), EnumPath);
        EnumRow->SetStringField(TEXT("class_path"), Enum->GetClass()->GetPathName());
        EnumRow->SetStringField(TEXT("cpp_type"), Enum->CppType);
        EnumRow->SetStringField(TEXT("display_name"), Enum->GetDisplayNameText().ToString());
        EnumRow->SetNumberField(TEXT("entry_count"), EntryCount);
        EnumRow->SetBoolField(TEXT("contains_existing_max"), Enum->ContainsExistingMax());
        if (!EnumsWriter.Write(EnumRow))
        {
            OutError = TEXT("failed writing Blueprint enum ") + EnumPath;
            SaveManifest(OutputDir, Counts, false, OutError);
            return false;
        }
        ++Counts.Enums;

        for (int32 Index = 0; Index < EntryCount; ++Index)
        {
            const FString RawName = Enum->GetNameStringByIndex(Index);
            const FString AuthoredName = Enum->GetAuthoredNameStringByIndex(Index);
            const FString DisplayName = Enum->GetDisplayNameTextByIndex(Index).ToString();
            TSharedRef<FJsonObject> EntryRow = MakeShared<FJsonObject>();
            EntryRow->SetStringField(TEXT("enum_path"), EnumPath);
            EntryRow->SetNumberField(TEXT("enum_index"), Index);
            EntryRow->SetNumberField(TEXT("numeric_value"), static_cast<double>(Enum->GetValueByIndex(Index)));
            EntryRow->SetStringField(TEXT("raw_name"), RawName);
            EntryRow->SetStringField(TEXT("authored_name"), AuthoredName);
            EntryRow->SetStringField(TEXT("display_name"), DisplayName);
            EntryRow->SetStringField(TEXT("tooltip"), Enum->GetToolTipTextByIndex(Index).ToString());
            EntryRow->SetBoolField(TEXT("hidden"), Enum->HasMetaData(TEXT("Hidden"), Index));
            EntryRow->SetBoolField(TEXT("is_max"), RawName.EndsWith(TEXT("_MAX")));
            if (!EntriesWriter.Write(EntryRow))
            {
                OutError = TEXT("failed writing Blueprint enum entry for ") + EnumPath;
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
            ++Counts.Entries;
        }
    }

    if (!SaveManifest(OutputDir, Counts, true, FString()))
    {
        OutError = TEXT("could not write blueprint_enum_manifest.json");
        return false;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolBlueprintEnums: enums=%lld entries=%lld"),
        Counts.Enums,
        Counts.Entries);
    return true;
}

static void OnPostEngineInit()
{
    FString RunCommandlet;
    FParse::Value(FCommandLine::Get(), TEXT("run="), RunCommandlet);
    if (!RunCommandlet.Equals(TEXT("UnrealAssetToolWorld"), ESearchCase::IgnoreCase))
    {
        return;
    }

    FString Error;
    if (!RunBlueprintEnumScan(Error))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolBlueprintEnums: %s"), *Error);
    }
}

struct FBlueprintEnumScannerBootstrap
{
    FBlueprintEnumScannerBootstrap()
    {
        FCoreDelegates::GetOnPostEngineInit().AddStatic(&OnPostEngineInit);
    }
};

static FBlueprintEnumScannerBootstrap GBlueprintEnumScannerBootstrap;
}
