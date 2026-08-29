#include "UnrealAssetToolWorldCommandlet.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "Algo/Unique.h"
#include "Components/ActorComponent.h"
#include "Components/SceneComponent.h"
#include "Engine/Blueprint.h"
#include "Engine/Level.h"
#include "Engine/LevelStreaming.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UnrealType.h"
#include "WorldPartition/DataLayer/DataLayerAsset.h"
#include "WorldPartition/DataLayer/DataLayerInstance.h"
#include "WorldPartition/DataLayer/DataLayerInstanceNames.h"
#include "WorldPartition/DataLayer/WorldDataLayers.h"
#include "WorldPartition/WorldPartition.h"
#include "WorldPartition/WorldPartitionActorDesc.h"
#include "WorldPartition/WorldPartitionActorDescInstance.h"
#include "WorldPartition/WorldPartitionHelpers.h"

namespace UnrealAssetToolWorld
{
constexpr int32 WorldSchemaVersion = 12;
constexpr int32 MaxReferenceDepth = 8;
constexpr int32 MaxReferenceRowsPerOwner = 4096;
constexpr int32 MaxExportTextChars = 32768;

struct FWorldCounts
{
    int64 Worlds = 0;
    int64 Levels = 0;
    int64 StreamingRelationships = 0;
    int64 Actors = 0;
    int64 Components = 0;
    int64 InstanceOverrides = 0;
    int64 References = 0;
    int64 DataLayers = 0;
    int64 WorldPartitionWorlds = 0;
    int64 WorldPartitionAlreadyInitialized = 0;
    int64 WorldPartitionInitializedForScan = 0;
    int64 WorldPartitionInitializeUnavailable = 0;
    int64 WorldPartitionInitializeFailed = 0;
    int64 WorldPartitionActorDescs = 0;
};

struct FWorldPartitionScanResult
{
    bool bPresent = false;
    bool bInitializedBeforeScan = false;
    bool bCanInitialize = false;
    bool bInitializedForScan = false;
    bool bInitializedForDescriptorWalk = false;
    int64 DescriptorCount = 0;
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
        const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> JsonWriter =
            TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);
        if (!FJsonSerializer::Serialize(Object, JsonWriter))
        {
            return false;
        }

        Line.AppendChar(TEXT('\n'));
        FTCHARToUTF8 Utf8(*Line);
        Archive->Serialize((void*)Utf8.Get(), Utf8.Length());
        return !Archive->IsError();
    }

    void Close()
    {
        if (Archive.IsValid())
        {
            Archive->Close();
            Archive.Reset();
        }
    }

    ~FJsonlWriter()
    {
        Close();
    }

private:
    FString Path;
    TUniquePtr<FArchive> Archive;
};

static FString ObjectPath(const UObject* Object)
{
    return Object ? Object->GetPathName() : FString();
}

static FString ClassPath(const UObject* Object)
{
    return (Object && Object->GetClass()) ? Object->GetClass()->GetPathName() : FString();
}

static FString ClassPath(const UClass* Class)
{
    return Class ? Class->GetPathName() : FString();
}

static FString GuidString(const FGuid& Guid)
{
    return Guid.IsValid() ? Guid.ToString(EGuidFormats::DigitsWithHyphensLower) : FString();
}

static TArray<TSharedPtr<FJsonValue>> NamesToJson(const TArray<FName>& Names)
{
    TArray<FString> Values;
    Values.Reserve(Names.Num());
    for (const FName Name : Names)
    {
        if (!Name.IsNone())
        {
            Values.Add(Name.ToString());
        }
    }
    Values.Sort();
    Values.SetNum(Algo::Unique(Values));

    TArray<TSharedPtr<FJsonValue>> Result;
    Result.Reserve(Values.Num());
    for (const FString& Value : Values)
    {
        Result.Add(MakeShared<FJsonValueString>(Value));
    }
    return Result;
}

static TArray<TSharedPtr<FJsonValue>> StringsToJson(TArray<FString> Values)
{
    Values.RemoveAll([](const FString& Value) { return Value.IsEmpty(); });
    Values.Sort();
    Values.SetNum(Algo::Unique(Values));

    TArray<TSharedPtr<FJsonValue>> Result;
    Result.Reserve(Values.Num());
    for (const FString& Value : Values)
    {
        Result.Add(MakeShared<FJsonValueString>(Value));
    }
    return Result;
}

static TSharedRef<FJsonObject> TransformJson(const FTransform& Transform)
{
    const FVector Location = Transform.GetLocation();
    const FQuat Rotation = Transform.GetRotation();
    const FVector Scale = Transform.GetScale3D();

    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();

    TSharedRef<FJsonObject> LocationJson = MakeShared<FJsonObject>();
    LocationJson->SetNumberField(TEXT("x"), Location.X);
    LocationJson->SetNumberField(TEXT("y"), Location.Y);
    LocationJson->SetNumberField(TEXT("z"), Location.Z);
    Result->SetObjectField(TEXT("location"), LocationJson);

    TSharedRef<FJsonObject> RotationJson = MakeShared<FJsonObject>();
    RotationJson->SetNumberField(TEXT("x"), Rotation.X);
    RotationJson->SetNumberField(TEXT("y"), Rotation.Y);
    RotationJson->SetNumberField(TEXT("z"), Rotation.Z);
    RotationJson->SetNumberField(TEXT("w"), Rotation.W);
    Result->SetObjectField(TEXT("rotation_quat"), RotationJson);

    TSharedRef<FJsonObject> ScaleJson = MakeShared<FJsonObject>();
    ScaleJson->SetNumberField(TEXT("x"), Scale.X);
    ScaleJson->SetNumberField(TEXT("y"), Scale.Y);
    ScaleJson->SetNumberField(TEXT("z"), Scale.Z);
    Result->SetObjectField(TEXT("scale"), ScaleJson);

    return Result;
}

static TSharedRef<FJsonObject> BoxJson(const FBox& Box)
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetBoolField(TEXT("valid"), Box.IsValid != 0);
    if (Box.IsValid)
    {
        TSharedRef<FJsonObject> Min = MakeShared<FJsonObject>();
        Min->SetNumberField(TEXT("x"), Box.Min.X);
        Min->SetNumberField(TEXT("y"), Box.Min.Y);
        Min->SetNumberField(TEXT("z"), Box.Min.Z);
        Result->SetObjectField(TEXT("min"), Min);

        TSharedRef<FJsonObject> Max = MakeShared<FJsonObject>();
        Max->SetNumberField(TEXT("x"), Box.Max.X);
        Max->SetNumberField(TEXT("y"), Box.Max.Y);
        Max->SetNumberField(TEXT("z"), Box.Max.Z);
        Result->SetObjectField(TEXT("max"), Max);
    }
    return Result;
}

static bool IsRejectedSerializedProperty(const FProperty* Property)
{
    if (!Property)
    {
        return true;
    }

    constexpr EPropertyFlags RejectedFlags =
        CPF_Transient |
        CPF_DuplicateTransient |
        CPF_NonPIEDuplicateTransient |
        CPF_Deprecated |
        CPF_SkipSerialization;

    if (Property->HasAnyPropertyFlags(RejectedFlags))
    {
        return true;
    }

    static const TSet<FName> StructuralNames = {
        TEXT("RootComponent"),
        TEXT("InstanceComponents"),
        TEXT("BlueprintCreatedComponents"),
        TEXT("OwnedComponents"),
        TEXT("AttachParent"),
        TEXT("AttachChildren")
    };

    return StructuralNames.Contains(Property->GetFName());
}

static bool ShouldInspectReferenceProperty(const FProperty* Property)
{
    if (IsRejectedSerializedProperty(Property))
    {
        return false;
    }

    // References are useful even when the property is Blueprint-visible but
    // not directly editable on a placed instance.
    return Property->HasAnyPropertyFlags(CPF_Edit | CPF_BlueprintVisible);
}

static bool ShouldEmitInstanceOverride(const FProperty* Property)
{
    if (IsRejectedSerializedProperty(Property))
    {
        return false;
    }

    // "Authored placed-instance override" means a property the editor can
    // actually author on the instance. Blueprint-visible-only state is not
    // enough, and component/subobject pointer instancing must not masquerade
    // as a user-authored override simply because the instance pointer differs
    // from the class/archetype pointer.
    if (!Property->HasAnyPropertyFlags(CPF_Edit))
    {
        return false;
    }

    constexpr EPropertyFlags NonInstanceEditableFlags =
        CPF_DisableEditOnInstance |
        CPF_EditConst |
        CPF_InstancedReference;

    return !Property->HasAnyPropertyFlags(NonInstanceEditableFlags);
}

static FString ExportPropertyValue(
    const FProperty* Property,
    const UObject* Object,
    const UObject* Baseline,
    int32 ArrayIndex,
    bool& bOutTruncated)
{
    bOutTruncated = false;
    FString Value;
    if (!Property || !Object)
    {
        return Value;
    }

    Property->ExportText_InContainer(
        ArrayIndex,
        Value,
        Object,
        Baseline,
        const_cast<UObject*>(Object),
        PPF_None,
        const_cast<UObject*>(Object));

    if (Value.Len() > MaxExportTextChars)
    {
        Value.LeftInline(MaxExportTextChars, EAllowShrinking::No);
        bOutTruncated = true;
    }
    return Value;
}

static bool PropertyDiffers(
    const FProperty* Property,
    const UObject* Object,
    const UObject* Baseline,
    int32 ArrayIndex)
{
    if (!Property || !Object)
    {
        return false;
    }
    if (!Baseline || Baseline->GetClass() != Object->GetClass())
    {
        return true;
    }
    return !Property->Identical_InContainer(Object, Baseline, ArrayIndex, PPF_None);
}

static FString TargetKind(const UObject* Object)
{
    if (!Object)
    {
        return TEXT("none");
    }
    if (Object->IsA<AActor>())
    {
        return TEXT("actor");
    }
    if (Object->IsA<UActorComponent>())
    {
        return TEXT("component");
    }
    if (Object->IsAsset())
    {
        return TEXT("asset");
    }
    if (Object->IsA<UClass>())
    {
        return TEXT("class");
    }
    return TEXT("object");
}

struct FReferenceEmitContext
{
    FString WorldPath;
    FString ActorPath;
    FString OwnerKind;
    FString OwnerPath;
    FString RootProperty;
    bool bRootIsOverride = false;
    int32 RowsForOwner = 0;
    FJsonlWriter* Writer = nullptr;
    FWorldCounts* Counts = nullptr;
};

static void EmitHardReference(
    FReferenceEmitContext& Context,
    const FString& PropertyPath,
    const UObject* Target)
{
    if (!Target || !Context.Writer || !Context.Counts || Context.RowsForOwner >= MaxReferenceRowsPerOwner)
    {
        return;
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("world_path"), Context.WorldPath);
    Row->SetStringField(TEXT("actor_path"), Context.ActorPath);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetStringField(TEXT("owner_path"), Context.OwnerPath);
    Row->SetStringField(TEXT("root_property"), Context.RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), TEXT("hard_object"));
    Row->SetStringField(TEXT("target_path"), ObjectPath(Target));
    Row->SetStringField(TEXT("target_class"), ClassPath(Target));
    Row->SetStringField(TEXT("target_kind"), TargetKind(Target));
    Row->SetBoolField(TEXT("authored_override"), Context.bRootIsOverride);
    Context.Writer->Write(Row);
    ++Context.RowsForOwner;
    ++Context.Counts->References;
}

static void EmitSoftReference(
    FReferenceEmitContext& Context,
    const FString& PropertyPath,
    const FSoftObjectPath& Target)
{
    if (Target.IsNull() || !Context.Writer || !Context.Counts || Context.RowsForOwner >= MaxReferenceRowsPerOwner)
    {
        return;
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("world_path"), Context.WorldPath);
    Row->SetStringField(TEXT("actor_path"), Context.ActorPath);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetStringField(TEXT("owner_path"), Context.OwnerPath);
    Row->SetStringField(TEXT("root_property"), Context.RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), TEXT("soft_object"));
    Row->SetStringField(TEXT("target_path"), Target.ToString());
    Row->SetStringField(TEXT("target_class"), FString());
    Row->SetStringField(TEXT("target_kind"), TEXT("soft_object"));
    Row->SetBoolField(TEXT("authored_override"), Context.bRootIsOverride);
    Context.Writer->Write(Row);
    ++Context.RowsForOwner;
    ++Context.Counts->References;
}

static void CollectReferencesFromValue(
    const FProperty* Property,
    const void* ValueAddress,
    const FString& PropertyPath,
    int32 Depth,
    FReferenceEmitContext& Context)
{
    if (!Property || !ValueAddress || Depth > MaxReferenceDepth || Context.RowsForOwner >= MaxReferenceRowsPerOwner)
    {
        return;
    }

    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* SoftPtr = static_cast<const FSoftObjectPtr*>(ValueAddress);
        if (SoftPtr)
        {
            EmitSoftReference(Context, PropertyPath, SoftPtr->ToSoftObjectPath());
        }
        return;
    }

    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        EmitHardReference(Context, PropertyPath, ObjectProperty->GetObjectPropertyValue(ValueAddress));
        return;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        if (!StructProperty->Struct)
        {
            return;
        }
        for (TFieldIterator<FProperty> It(StructProperty->Struct); It; ++It)
        {
            const FProperty* Inner = *It;
            if (!Inner || Inner->HasAnyPropertyFlags(CPF_Transient | CPF_Deprecated | CPF_SkipSerialization))
            {
                continue;
            }
            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValueAddress, StaticIndex);
                const FString Suffix = Inner->ArrayDim > 1
                    ? FString::Printf(TEXT(".%s[%d]"), *Inner->GetName(), StaticIndex)
                    : FString::Printf(TEXT(".%s"), *Inner->GetName());
                CollectReferencesFromValue(Inner, InnerValue, PropertyPath + Suffix, Depth + 1, Context);
            }
        }
        return;
    }

    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValueAddress);
        for (int32 Index = 0; Index < Helper.Num() && Context.RowsForOwner < MaxReferenceRowsPerOwner; ++Index)
        {
            const uint8* Element = Helper.GetRawPtr(Index);
            CollectReferencesFromValue(
                ArrayProperty->Inner,
                Element,
                FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                Depth + 1,
                Context);
        }
    }
}

static void ScanObjectProperties(
    const FString& WorldPath,
    const FString& ActorPath,
    const FString& OwnerKind,
    UObject* Object,
    FJsonlWriter& OverrideWriter,
    FJsonlWriter& ReferenceWriter,
    FWorldCounts& Counts)
{
    if (!Object || !Object->GetClass())
    {
        return;
    }

    UObject* Baseline = Object->GetArchetype();
    if (Baseline == Object)
    {
        Baseline = nullptr;
    }

    FReferenceEmitContext ReferenceContext;
    ReferenceContext.WorldPath = WorldPath;
    ReferenceContext.ActorPath = ActorPath;
    ReferenceContext.OwnerKind = OwnerKind;
    ReferenceContext.OwnerPath = ObjectPath(Object);
    ReferenceContext.Writer = &ReferenceWriter;
    ReferenceContext.Counts = &Counts;

    for (TFieldIterator<FProperty> It(Object->GetClass(), EFieldIteratorFlags::IncludeSuper); It; ++It)
    {
        const FProperty* Property = *It;
        if (!ShouldInspectReferenceProperty(Property))
        {
            continue;
        }

        const bool bCanBeAuthoredOverride = ShouldEmitInstanceOverride(Property);

        for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
        {
            const bool bDiffers =
                bCanBeAuthoredOverride &&
                PropertyDiffers(Property, Object, Baseline, StaticIndex);
            const FString PropertyPath = Property->ArrayDim > 1
                ? FString::Printf(TEXT("%s[%d]"), *Property->GetName(), StaticIndex)
                : Property->GetName();

            if (bDiffers)
            {
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("world_path"), WorldPath);
                Row->SetStringField(TEXT("actor_path"), ActorPath);
                Row->SetStringField(TEXT("owner_kind"), OwnerKind);
                Row->SetStringField(TEXT("owner_path"), ObjectPath(Object));
                Row->SetStringField(TEXT("owner_class"), ClassPath(Object));
                Row->SetStringField(TEXT("baseline_path"), ObjectPath(Baseline));
                Row->SetStringField(TEXT("baseline_class"), ClassPath(Baseline));
                Row->SetStringField(TEXT("property_name"), Property->GetName());
                Row->SetStringField(TEXT("property_path"), PropertyPath);
                Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
                Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
                Row->SetStringField(
                    TEXT("property_flags"),
                    FString::Printf(TEXT("%llu"), static_cast<unsigned long long>(Property->GetPropertyFlags())));

                bool bValueTruncated = false;
                bool bBaselineTruncated = false;
                Row->SetStringField(
                    TEXT("value"),
                    ExportPropertyValue(Property, Object, Baseline, StaticIndex, bValueTruncated));
                Row->SetStringField(
                    TEXT("baseline_value"),
                    Baseline
                        ? ExportPropertyValue(Property, Baseline, nullptr, StaticIndex, bBaselineTruncated)
                        : FString());
                Row->SetBoolField(TEXT("value_truncated"), bValueTruncated);
                Row->SetBoolField(TEXT("baseline_value_truncated"), bBaselineTruncated);
                OverrideWriter.Write(Row);
                ++Counts.InstanceOverrides;
            }

            const void* ValueAddress = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
            ReferenceContext.RootProperty = Property->GetName();
            ReferenceContext.bRootIsOverride = bDiffers;
            CollectReferencesFromValue(Property, ValueAddress, PropertyPath, 0, ReferenceContext);
        }
    }
}

static void RefreshSceneComponentWorldTransform(
    USceneComponent* Component,
    TSet<USceneComponent*>& Updating,
    TSet<USceneComponent*>& Updated)
{
    if (!Component || Updated.Contains(Component))
    {
        return;
    }

    // Guard against malformed/cyclic attachment data. Unreal normally
    // prevents this, but the scanner must not recurse forever on damaged data.
    if (Updating.Contains(Component))
    {
        return;
    }

    Updating.Add(Component);

    if (USceneComponent* Parent = Component->GetAttachParent())
    {
        RefreshSceneComponentWorldTransform(Parent, Updating, Updated);
    }

    // Loaded map assets are not active gameplay worlds, so ComponentToWorld
    // is frequently still the identity cache. Ask Unreal itself to rebuild it
    // from the serialized relative transform + attachment/socket state.
    Component->UpdateComponentToWorld();

    Updating.Remove(Component);
    Updated.Add(Component);
}

static void RefreshActorSceneComponentWorldTransforms(AActor* Actor)
{
    if (!Actor)
    {
        return;
    }

    TSet<USceneComponent*> Updating;
    TSet<USceneComponent*> Updated;

    for (UActorComponent* Component : Actor->GetComponents())
    {
        if (USceneComponent* SceneComponent = Cast<USceneComponent>(Component))
        {
            RefreshSceneComponentWorldTransform(SceneComponent, Updating, Updated);
        }
    }
}

static void ScanComponents(
    const FString& WorldPath,
    AActor* Actor,
    FJsonlWriter& ComponentWriter,
    FJsonlWriter& OverrideWriter,
    FJsonlWriter& ReferenceWriter,
    FWorldCounts& Counts)
{
    if (!Actor)
    {
        return;
    }

    TArray<UActorComponent*> Components;
    Components.Reserve(Actor->GetComponents().Num());
    for (UActorComponent* Component : Actor->GetComponents())
    {
        if (Component)
        {
            Components.Add(Component);
        }
    }
    Components.Sort([](const UActorComponent& A, const UActorComponent& B)
    {
        return A.GetPathName() < B.GetPathName();
    });

    for (UActorComponent* Component : Components)
    {
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("world_path"), WorldPath);
        Row->SetStringField(TEXT("actor_path"), ObjectPath(Actor));
        Row->SetStringField(TEXT("component_path"), ObjectPath(Component));
        Row->SetStringField(TEXT("component_name"), Component->GetName());
        Row->SetStringField(TEXT("component_class"), ClassPath(Component));
        Row->SetStringField(TEXT("archetype_path"), ObjectPath(Component->GetArchetype()));
        Row->SetNumberField(TEXT("creation_method"), static_cast<int32>(Component->CreationMethod));
        Row->SetArrayField(TEXT("tags"), NamesToJson(Component->ComponentTags));

        if (const USceneComponent* SceneComponent = Cast<USceneComponent>(Component))
        {
            const USceneComponent* Parent = SceneComponent->GetAttachParent();
            Row->SetBoolField(TEXT("is_scene_component"), true);
            Row->SetStringField(TEXT("attach_parent_component_path"), ObjectPath(Parent));
            Row->SetStringField(TEXT("attach_socket"), SceneComponent->GetAttachSocketName().ToString());
            Row->SetObjectField(TEXT("relative_transform"), TransformJson(SceneComponent->GetRelativeTransform()));
            Row->SetObjectField(TEXT("world_transform"), TransformJson(SceneComponent->GetComponentTransform()));
        }
        else
        {
            Row->SetBoolField(TEXT("is_scene_component"), false);
            Row->SetStringField(TEXT("attach_parent_component_path"), FString());
            Row->SetStringField(TEXT("attach_socket"), FString());
        }

        ComponentWriter.Write(Row);
        ++Counts.Components;

        ScanObjectProperties(
            WorldPath,
            ObjectPath(Actor),
            TEXT("component"),
            Component,
            OverrideWriter,
            ReferenceWriter,
            Counts);
    }
}

static void ScanActor(
    const FString& WorldPath,
    AActor* Actor,
    FJsonlWriter& ActorWriter,
    FJsonlWriter& ComponentWriter,
    FJsonlWriter& OverrideWriter,
    FJsonlWriter& ReferenceWriter,
    FWorldCounts& Counts)
{
    if (!Actor)
    {
        return;
    }

    RefreshActorSceneComponentWorldTransforms(Actor);

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("world_path"), WorldPath);
    Row->SetStringField(TEXT("level_path"), ObjectPath(Actor->GetLevel()));
    Row->SetStringField(TEXT("actor_guid"), GuidString(Actor->GetActorGuid()));
    Row->SetStringField(TEXT("actor_instance_guid"), GuidString(Actor->GetActorInstanceGuid()));
    Row->SetStringField(TEXT("actor_path"), ObjectPath(Actor));
    Row->SetStringField(TEXT("actor_name"), Actor->GetName());
    Row->SetStringField(TEXT("actor_label"), Actor->GetActorLabel(false));
    Row->SetStringField(TEXT("actor_class"), ClassPath(Actor));
    Row->SetStringField(TEXT("archetype_path"), ObjectPath(Actor->GetArchetype()));

    UClass* ActorClass = Actor->GetClass();
    UObject* GeneratedBy = ActorClass ? ActorClass->ClassGeneratedBy.Get() : nullptr;
    Row->SetStringField(TEXT("generated_class"), GeneratedBy ? ClassPath(ActorClass) : FString());
    Row->SetStringField(TEXT("blueprint_asset"), GeneratedBy ? ObjectPath(GeneratedBy) : FString());

    Row->SetStringField(TEXT("folder"), Actor->GetFolderPath().ToString());
    Row->SetStringField(TEXT("folder_guid"), GuidString(Actor->GetFolderGuid(false)));
    Row->SetStringField(TEXT("attach_parent_actor_path"), ObjectPath(Actor->GetAttachParentActor()));
    Row->SetStringField(TEXT("attach_parent_socket"), Actor->GetAttachParentSocketName().ToString());
    Row->SetStringField(TEXT("owner_actor_path"), ObjectPath(Actor->GetOwner()));
    Row->SetStringField(TEXT("child_actor_parent_path"), ObjectPath(Actor->GetParentActor()));
    Row->SetArrayField(TEXT("tags"), NamesToJson(Actor->Tags));
    Row->SetObjectField(TEXT("transform"), TransformJson(Actor->GetTransform()));
    Row->SetBoolField(TEXT("spatially_loaded"), Actor->GetIsSpatiallyLoaded());
    Row->SetStringField(TEXT("runtime_grid"), Actor->GetRuntimeGrid().ToString());

    const TArray<FName> DataLayerNames = Actor->GetDataLayerInstanceNames();
    Row->SetArrayField(TEXT("data_layer_instance_names"), NamesToJson(DataLayerNames));

    TArray<FString> DataLayerAssets;
    for (const UDataLayerAsset* Asset : Actor->GetDataLayerAssets(true))
    {
        if (Asset)
        {
            DataLayerAssets.Add(Asset->GetPathName());
        }
    }
    Row->SetArrayField(TEXT("data_layer_assets"), StringsToJson(MoveTemp(DataLayerAssets)));

    ActorWriter.Write(Row);
    ++Counts.Actors;

    ScanObjectProperties(
        WorldPath,
        ObjectPath(Actor),
        TEXT("actor"),
        Actor,
        OverrideWriter,
        ReferenceWriter,
        Counts);

    ScanComponents(
        WorldPath,
        Actor,
        ComponentWriter,
        OverrideWriter,
        ReferenceWriter,
        Counts);
}

static void ScanDataLayers(
    const FString& WorldPath,
    UWorld* World,
    FJsonlWriter& Writer,
    FWorldCounts& Counts)
{
    AWorldDataLayers* WorldDataLayers = World ? World->GetWorldDataLayers() : nullptr;
    if (!WorldDataLayers)
    {
        return;
    }

    TArray<const UDataLayerInstance*> Instances;
    WorldDataLayers->ForEachDataLayerInstance(
        [&Instances](UDataLayerInstance* Instance)
        {
            if (Instance)
            {
                Instances.Add(Instance);
            }
            return true;
        });
    Instances.Sort([](const UDataLayerInstance& A, const UDataLayerInstance& B)
    {
        return A.GetDataLayerFullName() < B.GetDataLayerFullName();
    });

    for (const UDataLayerInstance* Instance : Instances)
    {
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("world_path"), WorldPath);
        Row->SetStringField(TEXT("instance_path"), ObjectPath(Instance));
        Row->SetStringField(TEXT("instance_name"), Instance->GetName());
        Row->SetStringField(TEXT("data_layer_name"), Instance->GetFName().ToString());
        Row->SetStringField(TEXT("full_name"), Instance->GetDataLayerFullName());
        Row->SetStringField(TEXT("short_name"), Instance->GetDataLayerShortName());
        Row->SetStringField(TEXT("parent_instance_path"), ObjectPath(Instance->GetParent()));
        Row->SetBoolField(TEXT("runtime"), Instance->IsRuntime());
        Row->SetBoolField(TEXT("initially_loaded_in_editor"), Instance->IsInitiallyLoadedInEditor());
        Row->SetBoolField(TEXT("initially_visible"), Instance->IsInitiallyVisible());
        const UDataLayerAsset* Asset = Instance->GetAsset();
        Row->SetStringField(TEXT("asset_path"), ObjectPath(Asset));
        Row->SetStringField(TEXT("asset_class"), ClassPath(Asset));
        Writer.Write(Row);
        ++Counts.DataLayers;
    }
}

static FWorldPartitionScanResult ScanWorldPartition(
    const FString& WorldPath,
    UWorld* World,
    FJsonlWriter& Writer,
    FWorldCounts& Counts)
{
    FWorldPartitionScanResult Result;

    UWorldPartition* WorldPartition = World ? World->GetWorldPartition() : nullptr;
    if (!WorldPartition)
    {
        return Result;
    }

    Result.bPresent = true;
    ++Counts.WorldPartitionWorlds;

    Result.bInitializedBeforeScan = WorldPartition->IsInitialized();
    if (Result.bInitializedBeforeScan)
    {
        ++Counts.WorldPartitionAlreadyInitialized;
    }
    else
    {
        Result.bCanInitialize = WorldPartition->CanInitialize(World);
        if (Result.bCanInitialize)
        {
            // AssetData::GetAsset() can deserialize a partitioned UWorld without
            // running the normal ULevel::OnLevelLoaded -> UWorldPartition::Initialize
            // path. Initialize only the partition long enough to populate its
            // ActorDesc container instances. The descriptor walk below still does
            // not call GetActor() or ForEachActorWithLoading().
            WorldPartition->Initialize(World, FTransform::Identity);
            Result.bInitializedForScan = WorldPartition->IsInitialized();
            if (Result.bInitializedForScan)
            {
                ++Counts.WorldPartitionInitializedForScan;
            }
            else
            {
                ++Counts.WorldPartitionInitializeFailed;
            }
        }
        else
        {
            ++Counts.WorldPartitionInitializeUnavailable;
        }
    }

    Result.bInitializedForDescriptorWalk = WorldPartition->IsInitialized();

    if (!Result.bInitializedForDescriptorWalk)
    {
        UE_LOG(
            LogTemp,
            Warning,
            TEXT("WorldPartition descriptor walk unavailable: world=%s initialized_before=%d can_initialize=%d"),
            *WorldPath,
            Result.bInitializedBeforeScan ? 1 : 0,
            Result.bCanInitialize ? 1 : 0);
        return Result;
    }

    FWorldPartitionHelpers::ForEachActorDescInstance(
        WorldPartition,
        [&WorldPath, &Writer, &Counts, &Result](const FWorldPartitionActorDescInstance* Desc)
        {
            if (!Desc)
            {
                return true;
            }

            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("world_path"), WorldPath);
            Row->SetStringField(TEXT("actor_guid"), GuidString(Desc->GetGuid()));
            Row->SetStringField(TEXT("actor_name"), Desc->GetActorNameString());
            Row->SetStringField(TEXT("actor_label"), Desc->GetActorLabelString());
            Row->SetStringField(TEXT("actor_package"), Desc->GetActorPackage().ToString());
            Row->SetStringField(TEXT("actor_soft_path"), Desc->GetActorSoftPath().ToString());
            Row->SetStringField(TEXT("native_class"), ClassPath(Desc->GetActorNativeClass()));
            Row->SetStringField(TEXT("folder"), Desc->GetFolderPath().ToString());
            Row->SetStringField(TEXT("folder_guid"), GuidString(Desc->GetFolderGuid()));
            Row->SetStringField(TEXT("parent_actor_guid"), GuidString(Desc->GetParentActor()));
            Row->SetObjectField(TEXT("transform"), TransformJson(Desc->GetActorTransform()));
            Row->SetObjectField(TEXT("editor_bounds"), BoxJson(Desc->GetEditorBounds()));
            Row->SetBoolField(TEXT("spatially_loaded"), Desc->GetIsSpatiallyLoaded());
            Row->SetBoolField(TEXT("editor_only"), Desc->GetActorIsEditorOnly());
            Row->SetBoolField(TEXT("runtime_only"), Desc->GetActorIsRuntimeOnly());
            Row->SetBoolField(TEXT("hlod_relevant"), Desc->GetActorIsHLODRelevant());
            Row->SetArrayField(TEXT("data_layer_instance_names"), NamesToJson(Desc->GetDataLayerInstanceNames().ToArray()));

            TArray<FString> ReferenceGuids;
            for (const FGuid& ReferenceGuid : Desc->GetReferences())
            {
                ReferenceGuids.Add(GuidString(ReferenceGuid));
            }
            Row->SetArrayField(TEXT("actor_reference_guids"), StringsToJson(MoveTemp(ReferenceGuids)));

            if (const FWorldPartitionActorDesc* RawDesc = Desc->GetActorDesc())
            {
                Row->SetArrayField(TEXT("tags"), NamesToJson(RawDesc->GetTags()));
                Row->SetStringField(TEXT("runtime_grid"), RawDesc->GetRuntimeGrid().ToString());
                Row->SetObjectField(TEXT("runtime_bounds"), BoxJson(RawDesc->GetRuntimeBounds()));
            }
            else
            {
                Row->SetArrayField(TEXT("tags"), TArray<TSharedPtr<FJsonValue>>());
                Row->SetStringField(TEXT("runtime_grid"), FString());
            }

            Writer.Write(Row);
            ++Counts.WorldPartitionActorDescs;
            ++Result.DescriptorCount;
            return true;
        });

    UE_LOG(
        LogTemp,
        Display,
        TEXT("WorldPartition descriptor scan: world=%s initialized_before=%d initialized_for_scan=%d descs=%lld"),
        *WorldPath,
        Result.bInitializedBeforeScan ? 1 : 0,
        Result.bInitializedForScan ? 1 : 0,
        Result.DescriptorCount);

    if (Result.bInitializedForScan)
    {
        WorldPartition->Uninitialize();
    }

    return Result;
}

static void ScanWorld(
    const FAssetData& AssetData,
    UWorld* World,
    FJsonlWriter& WorldWriter,
    FJsonlWriter& LevelWriter,
    FJsonlWriter& ActorWriter,
    FJsonlWriter& ComponentWriter,
    FJsonlWriter& OverrideWriter,
    FJsonlWriter& ReferenceWriter,
    FJsonlWriter& DataLayerWriter,
    FJsonlWriter& WorldPartitionWriter,
    FWorldCounts& Counts)
{
    if (!World)
    {
        return;
    }

    const FString WorldPath = AssetData.GetSoftObjectPath().ToString();
    ULevel* PersistentLevel = World->PersistentLevel;
    UWorldPartition* WorldPartition = World->GetWorldPartition();

    TSharedRef<FJsonObject> WorldRow = MakeShared<FJsonObject>();
    WorldRow->SetStringField(TEXT("world_path"), WorldPath);
    WorldRow->SetStringField(TEXT("world_name"), World->GetName());
    WorldRow->SetStringField(TEXT("package_name"), AssetData.PackageName.ToString());
    WorldRow->SetStringField(TEXT("package_path"), AssetData.PackagePath.ToString());
    WorldRow->SetStringField(TEXT("persistent_level_path"), ObjectPath(PersistentLevel));
    WorldRow->SetBoolField(TEXT("world_partitioned"), WorldPartition != nullptr);
    WorldRow->SetStringField(TEXT("world_partition_path"), ObjectPath(WorldPartition));

    if (PersistentLevel)
    {
        TSharedRef<FJsonObject> LevelRow = MakeShared<FJsonObject>();
        LevelRow->SetStringField(TEXT("world_path"), WorldPath);
        LevelRow->SetStringField(TEXT("level_path"), ObjectPath(PersistentLevel));
        LevelRow->SetStringField(TEXT("level_name"), PersistentLevel->GetName());
        LevelRow->SetStringField(TEXT("level_package"), PersistentLevel->GetPackage()->GetName());
        LevelRow->SetStringField(TEXT("level_kind"), TEXT("persistent"));
        LevelRow->SetStringField(TEXT("streaming_owner_path"), FString());
        LevelRow->SetStringField(TEXT("target_world_package"), AssetData.PackageName.ToString());
        LevelWriter.Write(LevelRow);
        ++Counts.Levels;
    }

    TArray<ULevelStreaming*> StreamingLevels = World->GetStreamingLevels();
    StreamingLevels.RemoveAll([](const ULevelStreaming* Streaming) { return Streaming == nullptr; });
    StreamingLevels.Sort([](const ULevelStreaming& A, const ULevelStreaming& B)
    {
        return A.GetPathName() < B.GetPathName();
    });

    for (ULevelStreaming* Streaming : StreamingLevels)
    {
        TSharedRef<FJsonObject> LevelRow = MakeShared<FJsonObject>();
        LevelRow->SetStringField(TEXT("world_path"), WorldPath);
        LevelRow->SetStringField(TEXT("level_path"), ObjectPath(Streaming->GetLoadedLevel()));
        LevelRow->SetStringField(TEXT("level_name"), Streaming->GetWorldAssetPackageFName().ToString());
        LevelRow->SetStringField(TEXT("level_package"), Streaming->GetWorldAssetPackageFName().ToString());
        LevelRow->SetStringField(TEXT("level_kind"), TEXT("streaming_reference"));
        LevelRow->SetStringField(TEXT("streaming_owner_path"), ObjectPath(Streaming));
        LevelRow->SetStringField(TEXT("streaming_class"), ClassPath(Streaming));
        LevelRow->SetStringField(TEXT("target_world_package"), Streaming->GetWorldAssetPackageFName().ToString());
        LevelWriter.Write(LevelRow);
        ++Counts.Levels;
        ++Counts.StreamingRelationships;
    }

    if (PersistentLevel)
    {
        TArray<AActor*> Actors;
        Actors.Reserve(PersistentLevel->Actors.Num());
        for (AActor* Actor : PersistentLevel->Actors)
        {
            if (Actor)
            {
                Actors.Add(Actor);
            }
        }
        Actors.Sort([](const AActor& A, const AActor& B)
        {
            const FString AGuid = GuidString(A.GetActorGuid());
            const FString BGuid = GuidString(B.GetActorGuid());
            if (AGuid != BGuid)
            {
                return AGuid < BGuid;
            }
            return A.GetPathName() < B.GetPathName();
        });

        for (AActor* Actor : Actors)
        {
            ScanActor(
                WorldPath,
                Actor,
                ActorWriter,
                ComponentWriter,
                OverrideWriter,
                ReferenceWriter,
                Counts);
        }
    }

    ScanDataLayers(WorldPath, World, DataLayerWriter, Counts);

    const FWorldPartitionScanResult WorldPartitionScan =
        ScanWorldPartition(WorldPath, World, WorldPartitionWriter, Counts);

    WorldRow->SetBoolField(TEXT("world_partition_initialized_before_scan"), WorldPartitionScan.bInitializedBeforeScan);
    WorldRow->SetBoolField(TEXT("world_partition_can_initialize"), WorldPartitionScan.bCanInitialize);
    WorldRow->SetBoolField(TEXT("world_partition_initialized_for_scan"), WorldPartitionScan.bInitializedForScan);
    WorldRow->SetBoolField(TEXT("world_partition_initialized_for_descriptor_walk"), WorldPartitionScan.bInitializedForDescriptorWalk);
    WorldRow->SetNumberField(TEXT("world_partition_actor_desc_count"), WorldPartitionScan.DescriptorCount);
    WorldWriter.Write(WorldRow);
    ++Counts.Worlds;
}

static bool WriteManifest(const FString& OutputDir, const FWorldCounts& Counts)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), WorldSchemaVersion);
    Root->SetStringField(TEXT("schema_name"), TEXT("world"));
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolWorld"));
    Root->SetNumberField(TEXT("structural_schema_baseline"), 12);
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("project_name"), FApp::GetProjectName());
    Root->SetStringField(TEXT("project_dir"), FPaths::ConvertRelativePathToFull(FPaths::ProjectDir()));
    Root->SetStringField(
        TEXT("transform_policy"),
        TEXT("refresh ComponentToWorld from serialized relative/attachment state with USceneComponent::UpdateComponentToWorld before extraction"));
    Root->SetStringField(
        TEXT("instance_override_policy"),
        TEXT("CPF_Edit properties differing from exact archetype; excludes transient/deprecated/skip-serialization, DisableEditOnInstance, EditConst, InstancedReference and structural attachment/component arrays"));
    Root->SetStringField(
        TEXT("world_partition_descriptor_policy"),
        TEXT("temporarily initialize a deserialized UWorldPartition only when needed and CanInitialize succeeds; enumerate ActorDesc instances only; do not call GetActor or ForEachActorWithLoading; uninitialize afterward"));

    TSharedRef<FJsonObject> CountsJson = MakeShared<FJsonObject>();
    CountsJson->SetNumberField(TEXT("worlds"), Counts.Worlds);
    CountsJson->SetNumberField(TEXT("levels"), Counts.Levels);
    CountsJson->SetNumberField(TEXT("streaming_relationships"), Counts.StreamingRelationships);
    CountsJson->SetNumberField(TEXT("actors"), Counts.Actors);
    CountsJson->SetNumberField(TEXT("components"), Counts.Components);
    CountsJson->SetNumberField(TEXT("instance_overrides"), Counts.InstanceOverrides);
    CountsJson->SetNumberField(TEXT("references"), Counts.References);
    CountsJson->SetNumberField(TEXT("data_layers"), Counts.DataLayers);
    CountsJson->SetNumberField(TEXT("world_partition_worlds"), Counts.WorldPartitionWorlds);
    CountsJson->SetNumberField(TEXT("world_partition_already_initialized"), Counts.WorldPartitionAlreadyInitialized);
    CountsJson->SetNumberField(TEXT("world_partition_initialized_for_scan"), Counts.WorldPartitionInitializedForScan);
    CountsJson->SetNumberField(TEXT("world_partition_initialize_unavailable"), Counts.WorldPartitionInitializeUnavailable);
    CountsJson->SetNumberField(TEXT("world_partition_initialize_failed"), Counts.WorldPartitionInitializeFailed);
    CountsJson->SetNumberField(TEXT("world_partition_actor_descs"), Counts.WorldPartitionActorDescs);
    Root->SetObjectField(TEXT("counts"), CountsJson);

    TArray<TSharedPtr<FJsonValue>> Files;
    const TCHAR* Names[] = {
        TEXT("worlds.jsonl"),
        TEXT("world_levels.jsonl"),
        TEXT("world_actors.jsonl"),
        TEXT("world_components.jsonl"),
        TEXT("world_instance_properties.jsonl"),
        TEXT("world_references.jsonl"),
        TEXT("world_data_layers.jsonl"),
        TEXT("world_partition_actor_descs.jsonl")
    };
    for (const TCHAR* Name : Names)
    {
        Files.Add(MakeShared<FJsonValueString>(Name));
    }
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
        *FPaths::Combine(OutputDir, TEXT("world_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}
} // namespace UnrealAssetToolWorld

UUnrealAssetToolWorldCommandlet::UUnrealAssetToolWorldCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolWorldCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolWorld;

    FString OutputDir;
    if (!FParse::Value(*Params, TEXT("Output="), OutputDir))
    {
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool"));
    }
    OutputDir = FPaths::ConvertRelativePathToFull(OutputDir);
    FPaths::NormalizeDirectoryName(OutputDir);

    UE_LOG(LogTemp, Display, TEXT("UnrealAssetToolWorld schema %d"), WorldSchemaVersion);
    UE_LOG(LogTemp, Display, TEXT("world output: %s"), *OutputDir);

    IFileManager::Get().MakeDirectory(*OutputDir, true);

    FJsonlWriter WorldWriter;
    FJsonlWriter LevelWriter;
    FJsonlWriter ActorWriter;
    FJsonlWriter ComponentWriter;
    FJsonlWriter OverrideWriter;
    FJsonlWriter ReferenceWriter;
    FJsonlWriter DataLayerWriter;
    FJsonlWriter WorldPartitionWriter;

    const struct
    {
        FJsonlWriter* Writer;
        const TCHAR* Name;
    } Outputs[] = {
        {&WorldWriter, TEXT("worlds.jsonl")},
        {&LevelWriter, TEXT("world_levels.jsonl")},
        {&ActorWriter, TEXT("world_actors.jsonl")},
        {&ComponentWriter, TEXT("world_components.jsonl")},
        {&OverrideWriter, TEXT("world_instance_properties.jsonl")},
        {&ReferenceWriter, TEXT("world_references.jsonl")},
        {&DataLayerWriter, TEXT("world_data_layers.jsonl")},
        {&WorldPartitionWriter, TEXT("world_partition_actor_descs.jsonl")}
    };

    for (const auto& Output : Outputs)
    {
        if (!Output.Writer->Open(FPaths::Combine(OutputDir, Output.Name)))
        {
            UE_LOG(LogTemp, Error, TEXT("Could not open world output file: %s"), Output.Name);
            return 2;
        }
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

    FWorldCounts Counts;
    const FTopLevelAssetPath WorldClassPath = UWorld::StaticClass()->GetClassPathName();

    for (const FAssetData& Asset : Assets)
    {
        if (Asset.AssetClassPath != WorldClassPath)
        {
            continue;
        }

        const FString PackageName = Asset.PackageName.ToString();
        if (!PackageName.StartsWith(TEXT("/Game/")) && !PackageName.StartsWith(TEXT("/Plugins/")))
        {
            // Project plugins normally have their own mounted roots rather than /Plugins/.
            // Keep non-engine/non-script world assets too; only engine content is excluded.
            if (PackageName.StartsWith(TEXT("/Engine/")) || PackageName.StartsWith(TEXT("/Script/")))
            {
                continue;
            }
        }

        UE_LOG(LogTemp, Display, TEXT("world: %s"), *Asset.GetSoftObjectPath().ToString());
        UWorld* World = Cast<UWorld>(Asset.GetAsset());
        if (!World)
        {
            UE_LOG(LogTemp, Warning, TEXT("Could not load world asset: %s"), *Asset.GetSoftObjectPath().ToString());
            continue;
        }

        ScanWorld(
            Asset,
            World,
            WorldWriter,
            LevelWriter,
            ActorWriter,
            ComponentWriter,
            OverrideWriter,
            ReferenceWriter,
            DataLayerWriter,
            WorldPartitionWriter,
            Counts);
    }

    for (const auto& Output : Outputs)
    {
        Output.Writer->Close();
    }

    if (!WriteManifest(OutputDir, Counts))
    {
        UE_LOG(LogTemp, Error, TEXT("Could not write world_manifest.json"));
        return 3;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("world scan complete: worlds=%lld levels=%lld streaming=%lld actors=%lld components=%lld overrides=%lld refs=%lld data_layers=%lld wp_worlds=%lld wp_initialized_for_scan=%lld wp_descs=%lld"),
        Counts.Worlds,
        Counts.Levels,
        Counts.StreamingRelationships,
        Counts.Actors,
        Counts.Components,
        Counts.InstanceOverrides,
        Counts.References,
        Counts.DataLayers,
        Counts.WorldPartitionWorlds,
        Counts.WorldPartitionInitializedForScan,
        Counts.WorldPartitionActorDescs);

    return 0;
}
