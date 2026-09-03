#include "UnrealAssetToolWorldGeometryFoliageCommandlet.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "HAL/FileManager.h"
#include "InstancedFoliage.h"
#include "InstancedFoliageActor.h"
#include "Json.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"

namespace UnrealAssetToolWorldGeometryFoliage
{
static const TCHAR* InstancedFoliageActorClass = TEXT("/Script/Foliage.InstancedFoliageActor");

struct FCounts
{
    int64 RegistryCandidates = 0;
    int64 LoadFailures = 0;
    int64 FoliageActors = 0;
    int64 FoliageActorTypeInfos = 0;
    int64 FoliageInstances = 0;
};

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
        if (!Archive.IsValid()) return false;
        FString Line;
        const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
            TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);
        if (!FJsonSerializer::Serialize(Object, Writer)) return false;
        Line.AppendChar(TEXT('\n'));
        FTCHARToUTF8 Utf8(*Line);
        Archive->Serialize((void*)Utf8.Get(), Utf8.Length());
        return !Archive->IsError();
    }

    bool Close()
    {
        if (!Archive.IsValid()) return true;
        const bool bClosed = Archive->Close();
        const bool bOk = bClosed && !Archive->IsError();
        Archive.Reset();
        return bOk;
    }

    ~FJsonlWriter() { Close(); }

private:
    TUniquePtr<FArchive> Archive;
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
    if (!NormalizedDirectory.EndsWith(TEXT("/"))) NormalizedDirectory.AppendChar(TEXT('/'));
    return NormalizedFile.StartsWith(NormalizedDirectory, ESearchCase::IgnoreCase);
}

static bool AssetInScope(const FAssetData& Asset, const FString& ProjectDir, bool bIncludeEngine)
{
    if (bIncludeEngine) return true;
    FString Filename;
    FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &Filename, false);
    return !Filename.IsEmpty() && IsInsideDirectory(Filename, ProjectDir);
}

static FString ObjectPath(UObject* Object)
{
    return Object ? Object->GetPathName() : FString();
}

static FString ObjectClass(UObject* Object)
{
    return Object ? Object->GetClass()->GetPathName() : FString();
}

static TSharedRef<FJsonObject> Vector(const FVector& Value)
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetNumberField(TEXT("x"), Value.X);
    Result->SetNumberField(TEXT("y"), Value.Y);
    Result->SetNumberField(TEXT("z"), Value.Z);
    return Result;
}

static TSharedRef<FJsonObject> Vector3f(const FVector3f& Value)
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetNumberField(TEXT("x"), static_cast<double>(Value.X));
    Result->SetNumberField(TEXT("y"), static_cast<double>(Value.Y));
    Result->SetNumberField(TEXT("z"), static_cast<double>(Value.Z));
    return Result;
}

static TSharedRef<FJsonObject> Rotator(const FRotator& Value)
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetNumberField(TEXT("pitch"), Value.Pitch);
    Result->SetNumberField(TEXT("yaw"), Value.Yaw);
    Result->SetNumberField(TEXT("roll"), Value.Roll);
    return Result;
}

static bool WriteActor(
    const FAssetData& Asset,
    AInstancedFoliageActor* Actor,
    FJsonlWriter& Actors,
    FJsonlWriter& Infos,
    FJsonlWriter& Instances,
    FCounts& Counts)
{
    if (!Actor) return false;

    int32 InfoIndex = 0;
    bool bWriteOk = true;
    Actor->ForEachFoliageInfo([&](UFoliageType* FoliageType, FFoliageInfo& Info)
    {
        if (!bWriteOk) return false;

        TSharedRef<FJsonObject> InfoRow = MakeShared<FJsonObject>();
        InfoRow->SetStringField(TEXT("foliage_actor_path"), Actor->GetPathName());
        InfoRow->SetNumberField(TEXT("map_index"), InfoIndex);
        InfoRow->SetStringField(TEXT("foliage_type_path"), ObjectPath(FoliageType));
        InfoRow->SetStringField(TEXT("foliage_type_class"), ObjectClass(FoliageType));
        InfoRow->SetStringField(TEXT("info_struct"), TEXT("FFoliageInfo"));
        InfoRow->SetStringField(TEXT("capture_mode"), TEXT("native_editor_array"));
        InfoRow->SetBoolField(TEXT("instances_reflected_as_struct_array"), false);
        InfoRow->SetBoolField(TEXT("instances_captured_via_native_api"), true);
        InfoRow->SetNumberField(TEXT("implementation_type"), static_cast<int32>(Info.Type));
        InfoRow->SetStringField(TEXT("foliage_type_update_guid"), Info.FoliageTypeUpdateGuid.ToString(EGuidFormats::DigitsWithHyphens));
        InfoRow->SetNumberField(TEXT("instance_count"), Info.Instances.Num());
        InfoRow->SetNumberField(TEXT("placed_instance_count"), Info.GetPlacedInstanceCount());

        if (!Infos.Write(InfoRow))
        {
            bWriteOk = false;
            return false;
        }
        ++Counts.FoliageActorTypeInfos;

        for (int32 InstanceIndex = 0; InstanceIndex < Info.Instances.Num(); ++InstanceIndex)
        {
            const FFoliageInstance& Instance = Info.Instances[InstanceIndex];
            UObject* BaseComponent = Instance.BaseComponent;

            TSharedRef<FJsonObject> InstanceRow = MakeShared<FJsonObject>();
            InstanceRow->SetStringField(TEXT("foliage_actor_path"), Actor->GetPathName());
            InstanceRow->SetStringField(TEXT("foliage_type_path"), ObjectPath(FoliageType));
            InstanceRow->SetNumberField(TEXT("map_index"), InfoIndex);
            InstanceRow->SetNumberField(TEXT("instance_index"), InstanceIndex);
            InstanceRow->SetStringField(TEXT("instance_struct"), TEXT("FFoliageInstance"));
            InstanceRow->SetStringField(TEXT("capture_mode"), TEXT("native_editor_array"));
            InstanceRow->SetObjectField(TEXT("location"), Vector(Instance.Location));
            InstanceRow->SetObjectField(TEXT("rotation"), Rotator(Instance.Rotation));
            InstanceRow->SetObjectField(TEXT("pre_align_rotation"), Rotator(Instance.PreAlignRotation));
            InstanceRow->SetObjectField(TEXT("draw_scale3d"), Vector3f(Instance.DrawScale3D));
            InstanceRow->SetNumberField(TEXT("z_offset"), Instance.ZOffset);
            InstanceRow->SetNumberField(TEXT("flags"), static_cast<double>(Instance.Flags));
            InstanceRow->SetNumberField(TEXT("base_id"), Instance.BaseId);
            InstanceRow->SetStringField(TEXT("base_component_path"), ObjectPath(BaseComponent));
            InstanceRow->SetStringField(TEXT("base_component_class"), ObjectClass(BaseComponent));
            InstanceRow->SetStringField(TEXT("procedural_guid"), Instance.ProceduralGuid.ToString(EGuidFormats::DigitsWithHyphens));
            InstanceRow->SetBoolField(TEXT("procedural_guid_valid"), Instance.ProceduralGuid.IsValid());

            if (!Instances.Write(InstanceRow))
            {
                bWriteOk = false;
                return false;
            }
            ++Counts.FoliageInstances;
        }

        ++InfoIndex;
        return true;
    });

    if (!bWriteOk) return false;

    TSharedRef<FJsonObject> ActorRow = MakeShared<FJsonObject>();
    ActorRow->SetStringField(TEXT("foliage_actor_path"), Actor->GetPathName());
    ActorRow->SetStringField(TEXT("class_path"), Actor->GetClass()->GetPathName());
    ActorRow->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    ActorRow->SetStringField(TEXT("foliage_info_property"), TEXT("native:GetFoliageInfos"));
    ActorRow->SetStringField(TEXT("foliage_info_capture_mode"), TEXT("AInstancedFoliageActor::ForEachFoliageInfo"));
    ActorRow->SetNumberField(TEXT("foliage_info_count"), InfoIndex);
    if (!Actors.Write(ActorRow)) return false;
    ++Counts.FoliageActors;
    return true;
}

static bool PatchMainManifest(const FString& OutputDir, const FCounts& Counts, FString& OutError)
{
    const FString ManifestPath = FPaths::Combine(OutputDir, TEXT("world_geometry_capture_manifest.json"));
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *ManifestPath))
    {
        OutError = TEXT("could not read world_geometry_capture_manifest.json");
        return false;
    }

    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        OutError = TEXT("could not parse world_geometry_capture_manifest.json");
        return false;
    }

    TSharedPtr<FJsonObject> CountsObject = Root->GetObjectField(TEXT("counts"));
    if (!CountsObject.IsValid())
    {
        OutError = TEXT("world_geometry_capture_manifest.json missing counts object");
        return false;
    }

    CountsObject->SetNumberField(TEXT("foliage_actors"), Counts.FoliageActors);
    CountsObject->SetNumberField(TEXT("foliage_actor_type_infos"), Counts.FoliageActorTypeInfos);
    CountsObject->SetNumberField(TEXT("foliage_instances"), Counts.FoliageInstances);
    CountsObject->SetNumberField(TEXT("foliage_info_maps_opaque"), 0);
    Root->SetBoolField(TEXT("foliage_native_api_captured"), true);
    Root->SetStringField(
        TEXT("foliage_instance_capture_mode"),
        TEXT("AInstancedFoliageActor::ForEachFoliageInfo + FFoliageInfo::Instances"));

    FString OutputText;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&OutputText);
    if (!FJsonSerializer::Serialize(Root.ToSharedRef(), Writer))
    {
        OutError = TEXT("could not serialize patched world-geometry manifest");
        return false;
    }
    if (!FFileHelper::SaveStringToFile(
        OutputText,
        *ManifestPath,
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
    {
        OutError = TEXT("could not save patched world-geometry manifest");
        return false;
    }
    return true;
}

static bool RunCapture(const FString& OutputDir, bool bIncludeEngine, FCounts& Counts, FString& OutError)
{
    FJsonlWriter Actors;
    FJsonlWriter Infos;
    FJsonlWriter Instances;
    if (!Actors.Open(FPaths::Combine(OutputDir, TEXT("foliage_actors.jsonl"))) ||
        !Infos.Open(FPaths::Combine(OutputDir, TEXT("foliage_actor_type_infos.jsonl"))) ||
        !Instances.Open(FPaths::Combine(OutputDir, TEXT("foliage_instances.jsonl"))))
    {
        OutError = TEXT("could not open native foliage placement writers");
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.SearchAllAssets(true);

    TArray<FAssetData> Assets;
    Registry.GetAllAssets(Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString();
    });

    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    for (const FAssetData& Asset : Assets)
    {
        const FString ClassPath = Asset.AssetClassPath.ToString();
        if (ClassPath != InstancedFoliageActorClass) continue;
        if (!AssetInScope(Asset, ProjectDir, bIncludeEngine)) continue;
        ++Counts.RegistryCandidates;

        UObject* Object = Asset.GetAsset();
        AInstancedFoliageActor* Actor = Cast<AInstancedFoliageActor>(Object);
        if (!Actor)
        {
            ++Counts.LoadFailures;
            continue;
        }
        if (Actor->GetClass()->GetPathName() != InstancedFoliageActorClass)
        {
            OutError = TEXT("loaded InstancedFoliageActor class mismatch for ") + Asset.GetSoftObjectPath().ToString();
            Actors.Close();
            Infos.Close();
            Instances.Close();
            return false;
        }
        if (!WriteActor(Asset, Actor, Actors, Infos, Instances, Counts))
        {
            OutError = TEXT("failed writing native foliage placement for ") + Asset.GetSoftObjectPath().ToString();
            Actors.Close();
            Infos.Close();
            Instances.Close();
            return false;
        }
    }

    if (!Actors.Close() || !Infos.Close() || !Instances.Close())
    {
        OutError = TEXT("failed closing native foliage placement files");
        return false;
    }
    if (Counts.LoadFailures > 0)
    {
        OutError = FString::Printf(TEXT("%lld InstancedFoliageActor assets failed to load"), Counts.LoadFailures);
        return false;
    }
    return PatchMainManifest(OutputDir, Counts, OutError);
}
}

UUnrealAssetToolWorldGeometryFoliageCommandlet::UUnrealAssetToolWorldGeometryFoliageCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolWorldGeometryFoliageCommandlet::Main(const FString& Params)
{
    FString OutputDir;
    FParse::Value(*Params, TEXT("Output="), OutputDir);
    if (OutputDir.IsEmpty()) OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool/world-geometry-native-capture"));
    if (FPaths::IsRelative(OutputDir)) OutputDir = FPaths::ConvertRelativePathToFull(FPaths::ProjectDir(), OutputDir);
    FPaths::NormalizeDirectoryName(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    const bool bIncludeEngine = FParse::Param(*Params, TEXT("IncludeEngine"));
    UnrealAssetToolWorldGeometryFoliage::FCounts Counts;
    FString Error;
    const bool bSuccess = UnrealAssetToolWorldGeometryFoliage::RunCapture(OutputDir, bIncludeEngine, Counts, Error);

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolWorldGeometryFoliage: candidates=%lld foliage_actors=%lld foliage_infos=%lld foliage_instances=%lld"),
        Counts.RegistryCandidates,
        Counts.FoliageActors,
        Counts.FoliageActorTypeInfos,
        Counts.FoliageInstances);

    if (!bSuccess)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolWorldGeometryFoliage: %s"), *Error);
        return 4;
    }
    return 0;
}
