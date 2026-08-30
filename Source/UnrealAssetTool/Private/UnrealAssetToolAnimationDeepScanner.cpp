#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Animation/AnimCurveTypes.h"
#include "Animation/AnimData/IAnimationDataModel.h"
#include "Animation/AnimSequenceBase.h"
#include "Animation/MirrorDataTable.h"
#include "Curves/RichCurve.h"
#include "Dom/JsonObject.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/CommandLine.h"
#include "Misc/CoreDelegates.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolAnimationDeep
{
static constexpr int32 DeepSchemaVersion = 1;
static constexpr int32 MaxExportChars = 32768;

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
    int64 Curves = 0;
    int64 CurveKeys = 0;
    int64 InteractionAssets = 0;
    int64 InteractionItems = 0;
    int64 NormalizationSets = 0;
    int64 NormalizationDatabases = 0;
    int64 MirrorDataTables = 0;
    int64 MirrorRows = 0;
};

struct FWriters
{
    FJsonlWriter Curves;
    FJsonlWriter CurveKeys;
    FJsonlWriter InteractionAssets;
    FJsonlWriter InteractionItems;
    FJsonlWriter NormalizationSets;
    FJsonlWriter NormalizationDatabases;
    FJsonlWriter MirrorDataTables;
    FJsonlWriter MirrorRows;

    bool Open(const FString& OutputDir)
    {
        return Curves.Open(FPaths::Combine(OutputDir, TEXT("animation_curves.jsonl"))) &&
            CurveKeys.Open(FPaths::Combine(OutputDir, TEXT("animation_curve_keys.jsonl"))) &&
            InteractionAssets.Open(FPaths::Combine(OutputDir, TEXT("pose_search_interaction_assets.jsonl"))) &&
            InteractionItems.Open(FPaths::Combine(OutputDir, TEXT("pose_search_interaction_items.jsonl"))) &&
            NormalizationSets.Open(FPaths::Combine(OutputDir, TEXT("pose_search_normalization_sets.jsonl"))) &&
            NormalizationDatabases.Open(FPaths::Combine(OutputDir, TEXT("pose_search_normalization_databases.jsonl"))) &&
            MirrorDataTables.Open(FPaths::Combine(OutputDir, TEXT("mirror_data_tables.jsonl"))) &&
            MirrorRows.Open(FPaths::Combine(OutputDir, TEXT("mirror_data_table_rows.jsonl")));
    }
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

static FString ExportProperty(const FProperty* Property, const void* ValuePtr, UObject* Owner, bool& bTruncated)
{
    bTruncated = false;
    if (!Property || !ValuePtr)
    {
        return FString();
    }
    FString Value;
    Property->ExportTextItem_Direct(Value, ValuePtr, nullptr, Owner, PPF_None, nullptr);
    if (Value.Len() > MaxExportChars)
    {
        Value.LeftInline(MaxExportChars, EAllowShrinking::No);
        bTruncated = true;
    }
    return Value;
}

static FString ExportObjectProperty(UObject* Object, const FName PropertyName)
{
    if (!Object)
    {
        return FString();
    }
    const FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
    if (!Property)
    {
        return FString();
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    bool bTruncated = false;
    return ExportProperty(Property, ValuePtr, Object, bTruncated);
}

static UObject* GetStructObjectField(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    if (!Struct || !StructValue)
    {
        return nullptr;
    }
    const FObjectPropertyBase* Property = CastField<FObjectPropertyBase>(Struct->FindPropertyByName(FieldName));
    if (!Property)
    {
        return nullptr;
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructValue);
    return ValuePtr ? Property->GetObjectPropertyValue(ValuePtr) : nullptr;
}

static FString ExportStructField(UStruct* Struct, const void* StructValue, const FName FieldName, UObject* Owner)
{
    if (!Struct || !StructValue)
    {
        return FString();
    }
    const FProperty* Property = Struct->FindPropertyByName(FieldName);
    if (!Property)
    {
        return FString();
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructValue);
    bool bTruncated = false;
    return ExportProperty(Property, ValuePtr, Owner, bTruncated);
}

static bool WriteRichCurveKeys(
    const FString& AssetPath,
    const FString& CurveName,
    const FString& CurveType,
    const FString& Component,
    const FRichCurve& RichCurve,
    FWriters& Writers,
    FCounts& Counts)
{
    const TArray<FRichCurveKey>& Keys = RichCurve.GetConstRefOfKeys();
    for (int32 KeyIndex = 0; KeyIndex < Keys.Num(); ++KeyIndex)
    {
        const FRichCurveKey& Key = Keys[KeyIndex];
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetStringField(TEXT("curve_name"), CurveName);
        Row->SetStringField(TEXT("curve_type"), CurveType);
        Row->SetStringField(TEXT("component"), Component);
        Row->SetNumberField(TEXT("key_index"), KeyIndex);
        Row->SetNumberField(TEXT("time"), Key.Time);
        Row->SetNumberField(TEXT("value"), Key.Value);
        Row->SetNumberField(TEXT("interp_mode"), static_cast<int32>(Key.InterpMode.GetValue()));
        Row->SetNumberField(TEXT("tangent_mode"), static_cast<int32>(Key.TangentMode.GetValue()));
        Row->SetNumberField(TEXT("tangent_weight_mode"), static_cast<int32>(Key.TangentWeightMode.GetValue()));
        Row->SetNumberField(TEXT("arrive_tangent"), Key.ArriveTangent);
        Row->SetNumberField(TEXT("leave_tangent"), Key.LeaveTangent);
        Row->SetNumberField(TEXT("arrive_tangent_weight"), Key.ArriveTangentWeight);
        Row->SetNumberField(TEXT("leave_tangent_weight"), Key.LeaveTangentWeight);
        if (!Writers.CurveKeys.Write(Row))
        {
            return false;
        }
        ++Counts.CurveKeys;
    }
    return true;
}

static bool ScanCurves(UAnimSequenceBase* Sequence, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    if (!Sequence || !Sequence->IsDataModelValid())
    {
        return true;
    }
    const IAnimationDataModel* Model = Sequence->GetDataModel();
    if (!Model || !Model->HasBeenPopulated())
    {
        return true;
    }

    const TArray<FFloatCurve>& FloatCurves = Model->GetFloatCurves();
    for (int32 CurveIndex = 0; CurveIndex < FloatCurves.Num(); ++CurveIndex)
    {
        const FFloatCurve& Curve = FloatCurves[CurveIndex];
        const FString CurveName = Curve.GetName().ToString();
        const int32 KeyCount = Curve.FloatCurve.GetConstRefOfKeys().Num();
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetNumberField(TEXT("curve_index"), CurveIndex);
        Row->SetStringField(TEXT("curve_name"), CurveName);
        Row->SetStringField(TEXT("curve_type"), TEXT("float"));
        Row->SetNumberField(TEXT("curve_type_flags"), Curve.GetCurveTypeFlags());
        Row->SetNumberField(TEXT("key_count"), KeyCount);
        if (!Writers.Curves.Write(Row))
        {
            return false;
        }
        ++Counts.Curves;
        if (!WriteRichCurveKeys(AssetPath, CurveName, TEXT("float"), TEXT("value"), Curve.FloatCurve, Writers, Counts))
        {
            return false;
        }
    }

    static const TCHAR* TransformComponents[3][3] = {
        { TEXT("translation_x"), TEXT("translation_y"), TEXT("translation_z") },
        { TEXT("rotation_x"), TEXT("rotation_y"), TEXT("rotation_z") },
        { TEXT("scale_x"), TEXT("scale_y"), TEXT("scale_z") }
    };

    const TArray<FTransformCurve>& TransformCurves = Model->GetTransformCurves();
    for (int32 CurveIndex = 0; CurveIndex < TransformCurves.Num(); ++CurveIndex)
    {
        const FTransformCurve& Curve = TransformCurves[CurveIndex];
        const FString CurveName = Curve.GetName().ToString();
        int32 KeyCount = 0;
        for (int32 VectorIndex = 0; VectorIndex < 3; ++VectorIndex)
        {
            const FVectorCurve* VectorCurve = Curve.GetVectorCurveByIndex(VectorIndex);
            if (!VectorCurve)
            {
                continue;
            }
            for (int32 AxisIndex = 0; AxisIndex < 3; ++AxisIndex)
            {
                KeyCount += VectorCurve->FloatCurves[AxisIndex].GetConstRefOfKeys().Num();
            }
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetNumberField(TEXT("curve_index"), CurveIndex);
        Row->SetStringField(TEXT("curve_name"), CurveName);
        Row->SetStringField(TEXT("curve_type"), TEXT("transform"));
        Row->SetNumberField(TEXT("curve_type_flags"), Curve.GetCurveTypeFlags());
        Row->SetNumberField(TEXT("key_count"), KeyCount);
        if (!Writers.Curves.Write(Row))
        {
            return false;
        }
        ++Counts.Curves;

        for (int32 VectorIndex = 0; VectorIndex < 3; ++VectorIndex)
        {
            const FVectorCurve* VectorCurve = Curve.GetVectorCurveByIndex(VectorIndex);
            if (!VectorCurve)
            {
                continue;
            }
            for (int32 AxisIndex = 0; AxisIndex < 3; ++AxisIndex)
            {
                if (!WriteRichCurveKeys(
                    AssetPath,
                    CurveName,
                    TEXT("transform"),
                    TransformComponents[VectorIndex][AxisIndex],
                    VectorCurve->FloatCurves[AxisIndex],
                    Writers,
                    Counts))
                {
                    return false;
                }
            }
        }
    }
    return true;
}

static bool ScanInteractionAsset(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    FArrayProperty* ItemsProperty = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("Items")));
    FStructProperty* ItemStructProperty = ItemsProperty ? CastField<FStructProperty>(ItemsProperty->Inner) : nullptr;
    int32 ItemCount = 0;

    if (ItemsProperty && ItemStructProperty)
    {
        const void* ArrayValue = ItemsProperty->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(ItemsProperty, ArrayValue);
        ItemCount = Helper.Num();
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Item = Helper.GetRawPtr(Index);
            UObject* Animation = GetStructObjectField(ItemStructProperty->Struct, Item, TEXT("Animation"));
            UObject* PreviewMesh = GetStructObjectField(ItemStructProperty->Struct, Item, TEXT("PreviewMesh"));
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("interaction_path"), AssetPath);
            Row->SetNumberField(TEXT("item_index"), Index);
            Row->SetStringField(TEXT("role"), ExportStructField(ItemStructProperty->Struct, Item, TEXT("Role"), Object));
            Row->SetStringField(TEXT("animation_path"), Animation ? Animation->GetPathName() : FString());
            Row->SetStringField(TEXT("animation_class"), Animation ? Animation->GetClass()->GetPathName() : FString());
            Row->SetStringField(TEXT("preview_mesh_path"), PreviewMesh ? PreviewMesh->GetPathName() : FString());
            Row->SetStringField(TEXT("origin"), ExportStructField(ItemStructProperty->Struct, Item, TEXT("Origin"), Object));
            Row->SetStringField(TEXT("warping_weight_rotation"), ExportStructField(ItemStructProperty->Struct, Item, TEXT("WarpingWeightRotation"), Object));
            Row->SetStringField(TEXT("warping_weight_translation"), ExportStructField(ItemStructProperty->Struct, Item, TEXT("WarpingWeightTranslation"), Object));
            if (!Writers.InteractionItems.Write(Row))
            {
                return false;
            }
            ++Counts.InteractionItems;
        }
    }

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("interaction_path"), AssetPath);
    Summary->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetNumberField(TEXT("item_count"), ItemCount);
    Summary->SetStringField(TEXT("minimal_translation_weight"), ExportObjectProperty(Object, TEXT("MinimalTranslationWeight")));
    Summary->SetStringField(TEXT("warping_banking_weight"), ExportObjectProperty(Object, TEXT("WarpingBankingWeight")));
    if (!Writers.InteractionAssets.Write(Summary))
    {
        return false;
    }
    ++Counts.InteractionAssets;
    return true;
}

static bool ScanNormalizationSet(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    FArrayProperty* DatabasesProperty = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("Databases")));
    const FObjectPropertyBase* InnerObject = DatabasesProperty ? CastField<FObjectPropertyBase>(DatabasesProperty->Inner) : nullptr;
    int32 DatabaseCount = 0;

    if (DatabasesProperty && InnerObject)
    {
        const void* ArrayValue = DatabasesProperty->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(DatabasesProperty, ArrayValue);
        DatabaseCount = Helper.Num();
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            UObject* Database = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("normalization_set_path"), AssetPath);
            Row->SetNumberField(TEXT("database_index"), Index);
            Row->SetStringField(TEXT("database_path"), Database ? Database->GetPathName() : FString());
            if (!Writers.NormalizationDatabases.Write(Row))
            {
                return false;
            }
            ++Counts.NormalizationDatabases;
        }
    }

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("normalization_set_path"), AssetPath);
    Summary->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetNumberField(TEXT("database_count"), DatabaseCount);
    if (!Writers.NormalizationSets.Write(Summary))
    {
        return false;
    }
    ++Counts.NormalizationSets;
    return true;
}

static bool ScanMirrorDataTable(UMirrorDataTable* Table, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    if (!Table)
    {
        return true;
    }
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    const TArray<FName> RowNames = Table->GetRowNames();
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("mirror_table_path"), AssetPath);
    Summary->SetStringField(TEXT("class_path"), Table->GetClass()->GetPathName());
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("skeleton_path"), Table->Skeleton ? Table->Skeleton->GetPathName() : FString());
    Summary->SetNumberField(TEXT("mirror_axis"), static_cast<int32>(Table->MirrorAxis.GetValue()));
    Summary->SetNumberField(TEXT("row_count"), RowNames.Num());
    if (!Writers.MirrorDataTables.Write(Summary))
    {
        return false;
    }
    ++Counts.MirrorDataTables;

    for (int32 Index = 0; Index < RowNames.Num(); ++Index)
    {
        const FName RowName = RowNames[Index];
        const FMirrorTableRow* MirrorRow = Table->FindRow<FMirrorTableRow>(RowName, TEXT("UnrealAssetToolAnimationDeep"), false);
        if (!MirrorRow)
        {
            continue;
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("mirror_table_path"), AssetPath);
        Row->SetNumberField(TEXT("row_index"), Index);
        Row->SetStringField(TEXT("row_name"), RowName.ToString());
        Row->SetStringField(TEXT("name"), MirrorRow->Name.ToString());
        Row->SetStringField(TEXT("mirrored_name"), MirrorRow->MirroredName.ToString());
        Row->SetNumberField(TEXT("mirror_entry_type"), static_cast<int32>(MirrorRow->MirrorEntryType.GetValue()));
        Row->SetBoolField(TEXT("enabled"), MirrorRow->bEnabled);
        if (!Writers.MirrorRows.Write(Row))
        {
            return false;
        }
        ++Counts.MirrorRows;
    }
    return true;
}

static bool SaveManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), DeepSchemaVersion);
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolAnimationDeep"));
    Root->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);

    TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
    C->SetNumberField(TEXT("animation_curves"), Counts.Curves);
    C->SetNumberField(TEXT("animation_curve_keys"), Counts.CurveKeys);
    C->SetNumberField(TEXT("pose_search_interaction_assets"), Counts.InteractionAssets);
    C->SetNumberField(TEXT("pose_search_interaction_items"), Counts.InteractionItems);
    C->SetNumberField(TEXT("pose_search_normalization_sets"), Counts.NormalizationSets);
    C->SetNumberField(TEXT("pose_search_normalization_databases"), Counts.NormalizationDatabases);
    C->SetNumberField(TEXT("mirror_data_tables"), Counts.MirrorDataTables);
    C->SetNumberField(TEXT("mirror_data_table_rows"), Counts.MirrorRows);
    Root->SetObjectField(TEXT("counts"), C);

    TArray<TSharedPtr<FJsonValue>> Files;
    static const TCHAR* Names[] = {
        TEXT("animation_curves.jsonl"),
        TEXT("animation_curve_keys.jsonl"),
        TEXT("pose_search_interaction_assets.jsonl"),
        TEXT("pose_search_interaction_items.jsonl"),
        TEXT("pose_search_normalization_sets.jsonl"),
        TEXT("pose_search_normalization_databases.jsonl"),
        TEXT("mirror_data_tables.jsonl"),
        TEXT("mirror_data_table_rows.jsonl")
    };
    for (const TCHAR* Name : Names)
    {
        Files.Add(MakeShared<FJsonValueString>(Name));
    }
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
        *FPaths::Combine(OutputDir, TEXT("animation_deep_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunDeepScan(FString& OutError)
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

    const bool bIncludeEngine = FParse::Param(FCommandLine::Get(), TEXT("IncludeEngine"));
    const bool bIncludeSelf = FParse::Param(FCommandLine::Get(), TEXT("IncludeSelf"));
    FString ToolPluginDir;
    if (const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("UnrealAssetTool")); Plugin.IsValid())
    {
        ToolPluginDir = NormalizeAbsolutePath(Plugin->GetBaseDir());
    }

    FWriters Writers;
    FCounts Counts;
    if (!Writers.Open(OutputDir))
    {
        OutError = TEXT("could not create deep animation JSONL output files");
        SaveManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.SearchAllAssets(true);
    TArray<FAssetData> Assets;
    Registry.GetAllAssets(Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B) { return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString(); });

    for (const FAssetData& Asset : Assets)
    {
        const FString ClassPath = Asset.AssetClassPath.ToString();
        const bool bCurveAsset = ClassPath == TEXT("/Script/Engine.AnimSequence") ||
            ClassPath == TEXT("/Script/Engine.AnimMontage") ||
            ClassPath == TEXT("/Script/Engine.AnimComposite") ||
            ClassPath == TEXT("/Script/Engine.AnimStreamable");
        const bool bInteraction = ClassPath == TEXT("/Script/PoseSearch.PoseSearchInteractionAsset");
        const bool bNormalization = ClassPath == TEXT("/Script/PoseSearch.PoseSearchNormalizationSet");
        const bool bMirrorTable = ClassPath == TEXT("/Script/Engine.MirrorDataTable");
        if (!bCurveAsset && !bInteraction && !bNormalization && !bMirrorTable)
        {
            continue;
        }

        FString PackageFilename;
        const bool bHasDiskPackage = FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &PackageFilename, false);
        if (!bIncludeSelf && bHasDiskPackage && !ToolPluginDir.IsEmpty() && IsInsideDirectory(PackageFilename, ToolPluginDir))
        {
            continue;
        }
        if (!bIncludeEngine && (!bHasDiskPackage || !IsInsideDirectory(PackageFilename, ProjectDir)))
        {
            continue;
        }

        UObject* Object = Asset.GetAsset();
        if (!Object)
        {
            continue;
        }
        const FString AssetPath = Asset.GetSoftObjectPath().ToString();

        if (bCurveAsset)
        {
            if (!ScanCurves(Cast<UAnimSequenceBase>(Object), AssetPath, Writers, Counts))
            {
                OutError = TEXT("failed while scanning curves for ") + AssetPath;
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
        }
        else if (bInteraction)
        {
            if (!ScanInteractionAsset(Object, Asset, Writers, Counts))
            {
                OutError = TEXT("failed while scanning Pose Search interaction asset ") + AssetPath;
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
        }
        else if (bNormalization)
        {
            if (!ScanNormalizationSet(Object, Asset, Writers, Counts))
            {
                OutError = TEXT("failed while scanning Pose Search normalization set ") + AssetPath;
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
        }
        else if (bMirrorTable)
        {
            if (!ScanMirrorDataTable(Cast<UMirrorDataTable>(Object), Asset, Writers, Counts))
            {
                OutError = TEXT("failed while scanning mirror data table ") + AssetPath;
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
        }
    }

    if (!SaveManifest(OutputDir, Counts, true, FString()))
    {
        OutError = TEXT("could not write animation_deep_manifest.json");
        return false;
    }
    UE_LOG(LogTemp, Display,
        TEXT("UnrealAssetToolAnimationDeep: curves=%lld curve_keys=%lld interactions=%lld normalization_sets=%lld mirror_tables=%lld"),
        Counts.Curves,
        Counts.CurveKeys,
        Counts.InteractionAssets,
        Counts.NormalizationSets,
        Counts.MirrorDataTables);
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
    if (!RunDeepScan(Error))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolAnimationDeep: %s"), *Error);
    }
}

struct FDeepScannerBootstrap
{
    FDeepScannerBootstrap()
    {
        FCoreDelegates::GetOnPostEngineInit().AddStatic(&OnPostEngineInit);
    }
};

static FDeepScannerBootstrap GDeepScannerBootstrap;
}
