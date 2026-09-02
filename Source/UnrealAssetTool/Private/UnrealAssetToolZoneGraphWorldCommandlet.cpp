#include "UnrealAssetToolZoneGraphWorldCommandlet.h"

#include "Components/ActorComponent.h"
#include "Engine/Level.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/App.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/SoftObjectPath.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolZoneGraphWorld
{
constexpr int32 ZoneGraphWorldSchemaVersion = 1;
constexpr int32 MaxExportChars = 65536;

struct FCounts
{
    int64 WorldsRequested = 0;
    int64 WorldsLoaded = 0;
    int64 Shapes = 0;
    int64 Points = 0;
};

class FJsonlWriter
{
public:
    bool Open(const FString& Filename)
    {
        Path = Filename;
        IFileManager::Get().MakeDirectory(*FPaths::GetPath(Path), true);
        Archive.Reset(IFileManager::Get().CreateFileWriter(*Path));
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

    bool Close()
    {
        if (!Archive.IsValid())
        {
            return true;
        }
        const bool bClosed = Archive->Close();
        const bool bOk = bClosed && !Archive->IsError();
        Archive.Reset();
        return bOk;
    }

    ~FJsonlWriter()
    {
        Close();
    }

private:
    FString Path;
    TUniquePtr<FArchive> Archive;
};

static bool ClassInheritsName(const UClass* Class, const TCHAR* BaseName)
{
    for (const UClass* It = Class; It; It = It->GetSuperClass())
    {
        if (It->GetName().Equals(BaseName, ESearchCase::CaseSensitive))
        {
            return true;
        }
    }
    return false;
}

static FString ExportProperty(
    const FProperty* Property,
    const void* Value,
    UObject* Owner,
    bool& bTruncated)
{
    bTruncated = false;
    if (!Property || !Value)
    {
        return FString();
    }

    FString Text;
    Property->ExportTextItem_Direct(Text, Value, nullptr, Owner, PPF_None, nullptr);
    if (Text.Len() > MaxExportChars)
    {
        Text.LeftInline(MaxExportChars, EAllowShrinking::No);
        bTruncated = true;
    }
    return Text;
}

static FString ExportObjectField(UObject* Object, const TCHAR* Name)
{
    if (!Object)
    {
        return FString();
    }
    const FProperty* Property = Object->GetClass()->FindPropertyByName(FName(Name));
    if (!Property)
    {
        return FString();
    }
    bool bTruncated = false;
    return ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(Object), Object, bTruncated);
}

static FString ExportStructField(
    const UStruct* Struct,
    const void* StructValue,
    UObject* Owner,
    std::initializer_list<const TCHAR*> Names)
{
    if (!Struct || !StructValue)
    {
        return FString();
    }
    for (const TCHAR* Name : Names)
    {
        const FProperty* Property = Struct->FindPropertyByName(FName(Name));
        if (!Property)
        {
            continue;
        }
        bool bTruncated = false;
        return ExportProperty(
            Property,
            Property->ContainerPtrToValuePtr<void>(StructValue),
            Owner,
            bTruncated);
    }
    return FString();
}

static UActorComponent* FindZoneShapeComponent(AActor* Actor)
{
    if (!Actor)
    {
        return nullptr;
    }
    for (UActorComponent* Component : Actor->GetComponents())
    {
        if (Component && ClassInheritsName(Component->GetClass(), TEXT("ZoneShapeComponent")))
        {
            return Component;
        }
    }
    return nullptr;
}

static bool WriteShape(
    const FString& WorldPath,
    AActor* Shape,
    FJsonlWriter& ShapeWriter,
    FJsonlWriter& PointWriter,
    FCounts& Counts,
    FString& OutError)
{
    if (!Shape || !ClassInheritsName(Shape->GetClass(), TEXT("ZoneShape")))
    {
        return true;
    }

    UActorComponent* Component = FindZoneShapeComponent(Shape);
    if (!Component)
    {
        OutError = TEXT("ZoneShape has no ZoneShapeComponent: ") + Shape->GetPathName();
        return false;
    }

    const FArrayProperty* PointsProperty = CastField<FArrayProperty>(
        Component->GetClass()->FindPropertyByName(FName(TEXT("Points"))));
    const FStructProperty* PointStruct = PointsProperty
        ? CastField<FStructProperty>(PointsProperty->Inner)
        : nullptr;
    const void* PointsValue = PointsProperty
        ? PointsProperty->ContainerPtrToValuePtr<void>(Component)
        : nullptr;

    int32 PointCount = 0;
    if (PointsProperty && PointStruct && PointStruct->Struct && PointsValue)
    {
        FScriptArrayHelper Helper(PointsProperty, PointsValue);
        PointCount = Helper.Num();
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Point = Helper.GetRawPtr(Index);
            bool bTruncated = false;
            const FString RawValue = ExportProperty(
                PointsProperty->Inner,
                Point,
                Component,
                bTruncated);

            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("world_path"), WorldPath);
            Row->SetStringField(TEXT("shape_path"), Shape->GetPathName());
            Row->SetNumberField(TEXT("point_index"), Index);
            Row->SetStringField(
                TEXT("position"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("Position")}));
            Row->SetStringField(
                TEXT("rotation"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("Rotation")}));
            Row->SetStringField(
                TEXT("tangent_length"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("TangentLength")}));
            Row->SetStringField(
                TEXT("point_type"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("Type"), TEXT("PointType")}));
            Row->SetStringField(
                TEXT("lane_profile"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("LaneProfile")}));
            Row->SetStringField(
                TEXT("reverse_lane_profile"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("bReverseLaneProfile")}));
            Row->SetStringField(
                TEXT("lane_connection_restrictions"),
                ExportStructField(
                    PointStruct->Struct,
                    Point,
                    Component,
                    {TEXT("LaneConnectionRestrictions")}));
            Row->SetStringField(
                TEXT("inner_turn_radius"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("InnerTurnRadius")}));
            Row->SetStringField(TEXT("raw_value"), RawValue);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!PointWriter.Write(Row))
            {
                OutError = TEXT("failed writing ZoneShape point: ") + Shape->GetPathName();
                return false;
            }
            ++Counts.Points;
        }
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("world_path"), WorldPath);
    Row->SetStringField(TEXT("shape_path"), Shape->GetPathName());
    Row->SetStringField(
        TEXT("package_name"),
        Shape->GetOutermost() ? Shape->GetOutermost()->GetName() : FString());
    Row->SetStringField(TEXT("class_path"), Shape->GetClass()->GetPathName());
    Row->SetStringField(TEXT("component_path"), Component->GetPathName());
    Row->SetStringField(TEXT("component_class"), Component->GetClass()->GetPathName());
    Row->SetNumberField(TEXT("point_count"), PointCount);
    Row->SetStringField(TEXT("shape_type"), ExportObjectField(Component, TEXT("ShapeType")));
    Row->SetStringField(TEXT("lane_profile"), ExportObjectField(Component, TEXT("LaneProfile")));
    Row->SetStringField(TEXT("tags"), ExportObjectField(Component, TEXT("Tags")));
    Row->SetStringField(
        TEXT("reverse_lane_profile"),
        ExportObjectField(Component, TEXT("bReverseLaneProfile")));
    Row->SetStringField(
        TEXT("polygon_routing_type"),
        ExportObjectField(Component, TEXT("PolygonRoutingType")));
    Row->SetStringField(
        TEXT("relative_location"),
        ExportObjectField(Component, TEXT("RelativeLocation")));
    Row->SetStringField(
        TEXT("relative_rotation"),
        ExportObjectField(Component, TEXT("RelativeRotation")));
    Row->SetStringField(
        TEXT("per_point_lane_profiles"),
        ExportObjectField(Component, TEXT("PerPointLaneProfiles")));
    Row->SetStringField(TEXT("provenance"), TEXT("loaded_world_placed_actor_reflection"));
    Row->SetBoolField(TEXT("generated_lane_topology"), false);
    if (!ShapeWriter.Write(Row))
    {
        OutError = TEXT("failed writing ZoneShape: ") + Shape->GetPathName();
        return false;
    }
    ++Counts.Shapes;
    return true;
}

static bool ScanWorld(
    const FString& WorldPath,
    UWorld* World,
    FJsonlWriter& ShapeWriter,
    FJsonlWriter& PointWriter,
    FCounts& Counts,
    FString& OutError)
{
    if (!World || !World->PersistentLevel)
    {
        OutError = TEXT("loaded world has no persistent level: ") + WorldPath;
        return false;
    }

    TArray<AActor*> Shapes;
    for (AActor* Actor : World->PersistentLevel->Actors)
    {
        if (Actor && ClassInheritsName(Actor->GetClass(), TEXT("ZoneShape")))
        {
            Shapes.Add(Actor);
        }
    }
    Shapes.Sort([](const AActor& A, const AActor& B)
    {
        return A.GetPathName() < B.GetPathName();
    });

    for (AActor* Shape : Shapes)
    {
        if (!WriteShape(WorldPath, Shape, ShapeWriter, PointWriter, Counts, OutError))
        {
            return false;
        }
    }
    return true;
}

static bool WriteManifest(
    const FString& OutputDir,
    const FCounts& Counts,
    const TArray<FString>& RequestedWorlds,
    const TArray<FString>& LoadedWorlds,
    bool bSuccess,
    const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), ZoneGraphWorldSchemaVersion);
    Root->SetStringField(TEXT("schema_name"), TEXT("zonegraph_world"));
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolZoneGraphWorld"));
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("project_name"), FApp::GetProjectName());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetBoolField(TEXT("canonical_authored_zonegraph_capture"), true);
    Root->SetBoolField(TEXT("generated_lane_topology"), false);
    Root->SetStringField(TEXT("provenance"), TEXT("loaded_world_placed_actor_reflection"));

    TSharedRef<FJsonObject> CountsJson = MakeShared<FJsonObject>();
    CountsJson->SetNumberField(TEXT("worlds_requested"), Counts.WorldsRequested);
    CountsJson->SetNumberField(TEXT("worlds_loaded"), Counts.WorldsLoaded);
    CountsJson->SetNumberField(TEXT("zonegraph_shapes"), Counts.Shapes);
    CountsJson->SetNumberField(TEXT("zonegraph_shape_points"), Counts.Points);
    Root->SetObjectField(TEXT("counts"), CountsJson);

    TArray<TSharedPtr<FJsonValue>> RequestedJson;
    for (const FString& Value : RequestedWorlds)
    {
        RequestedJson.Add(MakeShared<FJsonValueString>(Value));
    }
    Root->SetArrayField(TEXT("requested_worlds"), RequestedJson);

    TArray<TSharedPtr<FJsonValue>> LoadedJson;
    for (const FString& Value : LoadedWorlds)
    {
        LoadedJson.Add(MakeShared<FJsonValueString>(Value));
    }
    Root->SetArrayField(TEXT("loaded_worlds"), LoadedJson);

    TArray<TSharedPtr<FJsonValue>> Files;
    Files.Add(MakeShared<FJsonValueString>(TEXT("zonegraph_shapes.jsonl")));
    Files.Add(MakeShared<FJsonValueString>(TEXT("zonegraph_shape_points.jsonl")));
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer))
    {
        return false;
    }
    Text.AppendChar(TEXT('\n'));
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("zonegraph_world_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}
} // namespace UnrealAssetToolZoneGraphWorld

UUnrealAssetToolZoneGraphWorldCommandlet::UUnrealAssetToolZoneGraphWorldCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolZoneGraphWorldCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolZoneGraphWorld;

    FString OutputDir;
    if (!FParse::Value(*Params, TEXT("Output="), OutputDir))
    {
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool/zonegraph-world-capture"));
    }
    OutputDir = FPaths::ConvertRelativePathToFull(OutputDir);
    FPaths::NormalizeDirectoryName(OutputDir);

    FString WorldListPath;
    if (!FParse::Value(*Params, TEXT("WorldList="), WorldListPath) || WorldListPath.IsEmpty())
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolZoneGraphWorld requires -WorldList=<file>"));
        return 2;
    }
    WorldListPath = FPaths::ConvertRelativePathToFull(WorldListPath);
    FPaths::NormalizeFilename(WorldListPath);

    TArray<FString> RequestedWorlds;
    if (!FFileHelper::LoadFileToStringArray(RequestedWorlds, *WorldListPath))
    {
        UE_LOG(LogTemp, Error, TEXT("Could not read ZoneGraph world list: %s"), *WorldListPath);
        return 3;
    }
    RequestedWorlds.RemoveAll([](const FString& Value)
    {
        return Value.TrimStartAndEnd().IsEmpty();
    });
    for (FString& Value : RequestedWorlds)
    {
        Value.TrimStartAndEndInline();
    }
    RequestedWorlds.Sort();

    IFileManager::Get().MakeDirectory(*OutputDir, true);
    FJsonlWriter ShapeWriter;
    FJsonlWriter PointWriter;
    if (!ShapeWriter.Open(FPaths::Combine(OutputDir, TEXT("zonegraph_shapes.jsonl"))) ||
        !PointWriter.Open(FPaths::Combine(OutputDir, TEXT("zonegraph_shape_points.jsonl"))))
    {
        UE_LOG(LogTemp, Error, TEXT("Could not create focused ZoneGraph output files"));
        return 4;
    }

    FCounts Counts;
    Counts.WorldsRequested = RequestedWorlds.Num();
    TArray<FString> LoadedWorlds;
    FString Error;
    bool bSuccess = true;

    for (const FString& WorldPath : RequestedWorlds)
    {
        UE_LOG(LogTemp, Display, TEXT("zonegraph world: %s"), *WorldPath);
        UObject* Loaded = FSoftObjectPath(WorldPath).TryLoad();
        UWorld* World = Cast<UWorld>(Loaded);
        if (!World)
        {
            Error = TEXT("could not load requested world: ") + WorldPath;
            bSuccess = false;
            break;
        }

        LoadedWorlds.Add(WorldPath);
        ++Counts.WorldsLoaded;
        if (!ScanWorld(WorldPath, World, ShapeWriter, PointWriter, Counts, Error))
        {
            bSuccess = false;
            break;
        }
    }

    if (!ShapeWriter.Close() || !PointWriter.Close())
    {
        if (Error.IsEmpty())
        {
            Error = TEXT("failed closing focused ZoneGraph JSONL outputs");
        }
        bSuccess = false;
    }

    if (!WriteManifest(OutputDir, Counts, RequestedWorlds, LoadedWorlds, bSuccess, Error))
    {
        UE_LOG(LogTemp, Error, TEXT("Could not write zonegraph_world_manifest.json"));
        return 5;
    }

    if (!bSuccess)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolZoneGraphWorld: %s"), *Error);
        return 6;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("ZoneGraph authored world capture complete: worlds=%lld/%lld shapes=%lld points=%lld generated_lane_topology=0"),
        Counts.WorldsLoaded,
        Counts.WorldsRequested,
        Counts.Shapes,
        Counts.Points);
    return 0;
}
