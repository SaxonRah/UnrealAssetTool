#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Animation/AnimationAsset.h"
#include "Animation/AnimCompositeBase.h"
#include "Animation/AnimMontage.h"
#include "Animation/AnimNotifies/AnimNotifyState.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimSequenceBase.h"
#include "Animation/AnimTypes.h"
#include "Animation/BlendSpace.h"
#include "Animation/Skeleton.h"
#include "Dom/JsonObject.h"
#include "Engine/SkeletalMeshSocket.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/CommandLine.h"
#include "Misc/CoreDelegates.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "ReferenceSkeleton.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolAnimation
{
static constexpr int32 AnimationSchemaVersion = 1;
static constexpr int32 MaxExportChars = 32768;
static constexpr int32 MaxReferenceDepth = 8;
static constexpr int32 MaxReferencesPerOwner = 4096;

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
    int64 Assets = 0;
    int64 Notifies = 0;
    int64 SyncMarkers = 0;
    int64 MontageSections = 0;
    int64 Segments = 0;
    int64 BlendSpaceAxes = 0;
    int64 BlendSpaceSamples = 0;
    int64 Skeletons = 0;
    int64 SkeletonBones = 0;
    int64 SkeletonSockets = 0;
    int64 PoseSearchDatabases = 0;
    int64 PoseSearchDatabaseAssets = 0;
    int64 PoseSearchSchemas = 0;
    int64 PoseSearchChannels = 0;
    int64 PoseSearchSchemaSkeletons = 0;
    int64 OptionalAssets = 0;
    int64 Properties = 0;
    int64 References = 0;
};

struct FWriters
{
    FJsonlWriter Assets;
    FJsonlWriter Notifies;
    FJsonlWriter SyncMarkers;
    FJsonlWriter MontageSections;
    FJsonlWriter Segments;
    FJsonlWriter BlendSpaceAxes;
    FJsonlWriter BlendSpaceSamples;
    FJsonlWriter Skeletons;
    FJsonlWriter SkeletonBones;
    FJsonlWriter SkeletonSockets;
    FJsonlWriter PoseSearchDatabases;
    FJsonlWriter PoseSearchDatabaseAssets;
    FJsonlWriter PoseSearchSchemas;
    FJsonlWriter PoseSearchChannels;
    FJsonlWriter PoseSearchSchemaSkeletons;
    FJsonlWriter OptionalAssets;
    FJsonlWriter Properties;
    FJsonlWriter References;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("animation_assets.jsonl"))) &&
            Notifies.Open(FPaths::Combine(OutputDir, TEXT("animation_notifies.jsonl"))) &&
            SyncMarkers.Open(FPaths::Combine(OutputDir, TEXT("animation_sync_markers.jsonl"))) &&
            MontageSections.Open(FPaths::Combine(OutputDir, TEXT("montage_sections.jsonl"))) &&
            Segments.Open(FPaths::Combine(OutputDir, TEXT("animation_segments.jsonl"))) &&
            BlendSpaceAxes.Open(FPaths::Combine(OutputDir, TEXT("blend_space_axes.jsonl"))) &&
            BlendSpaceSamples.Open(FPaths::Combine(OutputDir, TEXT("blend_space_samples.jsonl"))) &&
            Skeletons.Open(FPaths::Combine(OutputDir, TEXT("skeletons.jsonl"))) &&
            SkeletonBones.Open(FPaths::Combine(OutputDir, TEXT("skeleton_bones.jsonl"))) &&
            SkeletonSockets.Open(FPaths::Combine(OutputDir, TEXT("skeleton_sockets.jsonl"))) &&
            PoseSearchDatabases.Open(FPaths::Combine(OutputDir, TEXT("pose_search_databases.jsonl"))) &&
            PoseSearchDatabaseAssets.Open(FPaths::Combine(OutputDir, TEXT("pose_search_database_assets.jsonl"))) &&
            PoseSearchSchemas.Open(FPaths::Combine(OutputDir, TEXT("pose_search_schemas.jsonl"))) &&
            PoseSearchChannels.Open(FPaths::Combine(OutputDir, TEXT("pose_search_channels.jsonl"))) &&
            PoseSearchSchemaSkeletons.Open(FPaths::Combine(OutputDir, TEXT("pose_search_schema_skeletons.jsonl"))) &&
            OptionalAssets.Open(FPaths::Combine(OutputDir, TEXT("animation_optional_assets.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("animation_properties.jsonl"))) &&
            References.Open(FPaths::Combine(OutputDir, TEXT("animation_references.jsonl")));
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

static TSharedRef<FJsonObject> TransformJson(const FTransform& Transform)
{
    const FVector Location = Transform.GetLocation();
    const FQuat Rotation = Transform.GetRotation();
    const FVector Scale = Transform.GetScale3D();
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    TSharedRef<FJsonObject> L = MakeShared<FJsonObject>();
    L->SetNumberField(TEXT("x"), Location.X);
    L->SetNumberField(TEXT("y"), Location.Y);
    L->SetNumberField(TEXT("z"), Location.Z);
    Result->SetObjectField(TEXT("location"), L);
    TSharedRef<FJsonObject> R = MakeShared<FJsonObject>();
    R->SetNumberField(TEXT("x"), Rotation.X);
    R->SetNumberField(TEXT("y"), Rotation.Y);
    R->SetNumberField(TEXT("z"), Rotation.Z);
    R->SetNumberField(TEXT("w"), Rotation.W);
    Result->SetObjectField(TEXT("rotation_quat"), R);
    TSharedRef<FJsonObject> S = MakeShared<FJsonObject>();
    S->SetNumberField(TEXT("x"), Scale.X);
    S->SetNumberField(TEXT("y"), Scale.Y);
    S->SetNumberField(TEXT("z"), Scale.Z);
    Result->SetObjectField(TEXT("scale"), S);
    return Result;
}

static TArray<TSharedPtr<FJsonValue>> NamesJson(const TArray<FName>& Names)
{
    TArray<TSharedPtr<FJsonValue>> Result;
    Result.Reserve(Names.Num());
    for (const FName Name : Names)
    {
        Result.Add(MakeShared<FJsonValueString>(Name.ToString()));
    }
    return Result;
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

static UObject* GetObjectProperty(UObject* Object, const FName PropertyName)
{
    if (!Object)
    {
        return nullptr;
    }
    const FObjectPropertyBase* Property = CastField<FObjectPropertyBase>(Object->GetClass()->FindPropertyByName(PropertyName));
    if (!Property)
    {
        return nullptr;
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    return ValuePtr ? Property->GetObjectPropertyValue(ValuePtr) : nullptr;
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
    const FObjectPropertyBase* Field = CastField<FObjectPropertyBase>(Struct->FindPropertyByName(FieldName));
    if (!Field)
    {
        return nullptr;
    }
    const void* ValuePtr = Field->ContainerPtrToValuePtr<void>(StructValue);
    return ValuePtr ? Field->GetObjectPropertyValue(ValuePtr) : nullptr;
}

static FString ExportStructField(UStruct* Struct, const void* StructValue, const FName FieldName, UObject* Owner)
{
    if (!Struct || !StructValue)
    {
        return FString();
    }
    const FProperty* Field = Struct->FindPropertyByName(FieldName);
    if (!Field)
    {
        return FString();
    }
    const void* ValuePtr = Field->ContainerPtrToValuePtr<void>(StructValue);
    bool bTruncated = false;
    return ExportProperty(Field, ValuePtr, Owner, bTruncated);
}

static bool ShouldInspectProperty(const FProperty* Property)
{
    if (!Property)
    {
        return false;
    }
    constexpr EPropertyFlags Rejected = CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient | CPF_Deprecated | CPF_SkipSerialization;
    return !Property->HasAnyPropertyFlags(Rejected);
}

static bool WriteProperties(UObject* Object, const FString& AssetPath, const FString& OwnerKind, FWriters& Writers, FCounts& Counts)
{
    if (!Object)
    {
        return true;
    }
    TSet<FString> Seen;
    for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property))
            {
                continue;
            }
            const FString Key = Class->GetPathName() + TEXT("::") + Property->GetName();
            if (Seen.Contains(Key))
            {
                continue;
            }
            Seen.Add(Key);
            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
            bool bTruncated = false;
            const FString Value = ExportProperty(Property, ValuePtr, Object, bTruncated);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("asset_path"), AssetPath);
            Row->SetStringField(TEXT("owner_path"), Object->GetPathName());
            Row->SetStringField(TEXT("owner_kind"), OwnerKind);
            Row->SetStringField(TEXT("owner_class"), Object->GetClass()->GetPathName());
            Row->SetStringField(TEXT("declaring_type"), Class->GetPathName());
            Row->SetStringField(TEXT("property_name"), Property->GetName());
            Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
            Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
            Row->SetStringField(TEXT("value"), Value);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.Properties.Write(Row))
            {
                return false;
            }
            ++Counts.Properties;
        }
    }
    return true;
}

struct FReferenceContext
{
    FString AssetPath;
    FString OwnerPath;
    FString OwnerKind;
    FString RootProperty;
    int32 Rows = 0;
    FWriters* Writers = nullptr;
    FCounts* Counts = nullptr;
};

static void EmitReference(FReferenceContext& Context, const FString& PropertyPath, const FString& ReferenceKind, const FString& TargetPath, const FString& TargetClass)
{
    if (!Context.Writers || !Context.Counts || TargetPath.IsEmpty() || Context.Rows >= MaxReferencesPerOwner)
    {
        return;
    }
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), Context.AssetPath);
    Row->SetStringField(TEXT("owner_path"), Context.OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetStringField(TEXT("root_property"), Context.RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), ReferenceKind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (Context.Writers->References.Write(Row))
    {
        ++Context.Rows;
        ++Context.Counts->References;
    }
}

static void CollectReferences(const FProperty* Property, const void* ValuePtr, const FString& PropertyPath, int32 Depth, FReferenceContext& Context)
{
    if (!Property || !ValuePtr || Depth > MaxReferenceDepth || Context.Rows >= MaxReferencesPerOwner)
    {
        return;
    }
    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* SoftPtr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (SoftPtr && !SoftPtr->IsNull())
        {
            EmitReference(Context, PropertyPath, TEXT("soft_object"), SoftPtr->ToSoftObjectPath().ToString(), FString());
        }
        return;
    }
    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr);
        if (Target)
        {
            EmitReference(Context, PropertyPath, TEXT("hard_object"), Target->GetPathName(), Target->GetClass()->GetPathName());
        }
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
            if (!ShouldInspectProperty(Inner))
            {
                continue;
            }
            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const FString ChildPath = PropertyPath + TEXT(".") + Inner->GetName() + (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                CollectReferences(Inner, InnerValue, ChildPath, Depth + 1, Context);
            }
        }
        return;
    }
    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
        const int32 Limit = FMath::Min(Helper.Num(), 4096);
        for (int32 Index = 0; Index < Limit; ++Index)
        {
            CollectReferences(ArrayProperty->Inner, Helper.GetRawPtr(Index), FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index), Depth + 1, Context);
        }
        return;
    }
    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, ValuePtr);
        int32 EmittedIndex = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && EmittedIndex < 4096; ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            CollectReferences(SetProperty->ElementProp, Helper.GetElementPtr(Index), FString::Printf(TEXT("%s{%d}"), *PropertyPath, EmittedIndex++), Depth + 1, Context);
        }
        return;
    }
    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, ValuePtr);
        int32 EmittedIndex = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && EmittedIndex < 4096; ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            const FString Base = FString::Printf(TEXT("%s{%d}"), *PropertyPath, EmittedIndex++);
            CollectReferences(MapProperty->KeyProp, Helper.GetKeyPtr(Index), Base + TEXT(".key"), Depth + 1, Context);
            CollectReferences(MapProperty->ValueProp, Helper.GetValuePtr(Index), Base + TEXT(".value"), Depth + 1, Context);
        }
    }
}

static void WriteReferences(UObject* Object, const FString& AssetPath, const FString& OwnerKind, FWriters& Writers, FCounts& Counts)
{
    if (!Object)
    {
        return;
    }
    for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property))
            {
                continue;
            }
            FReferenceContext Context;
            Context.AssetPath = AssetPath;
            Context.OwnerPath = Object->GetPathName();
            Context.OwnerKind = OwnerKind;
            Context.RootProperty = Property->GetName();
            Context.Writers = &Writers;
            Context.Counts = &Counts;
            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
            {
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
                const FString Path = Property->GetName() + (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                CollectReferences(Property, ValuePtr, Path, 0, Context);
            }
        }
    }
}

static FString KindForClass(const FString& ClassPath)
{
    if (ClassPath == TEXT("/Script/Engine.AnimSequence")) return TEXT("anim_sequence");
    if (ClassPath == TEXT("/Script/Engine.AnimMontage")) return TEXT("anim_montage");
    if (ClassPath == TEXT("/Script/Engine.AnimComposite")) return TEXT("anim_composite");
    if (ClassPath == TEXT("/Script/Engine.AnimStreamable")) return TEXT("anim_streamable");
    if (ClassPath == TEXT("/Script/Engine.PoseAsset")) return TEXT("pose_asset");
    if (ClassPath == TEXT("/Script/Engine.Skeleton")) return TEXT("skeleton");
    if (ClassPath.Contains(TEXT("BlendSpace"))) return TEXT("blend_space");
    if (ClassPath.Contains(TEXT("PoseSearchDatabase"))) return TEXT("pose_search_database");
    if (ClassPath.Contains(TEXT("PoseSearchSchema"))) return TEXT("pose_search_schema");
    if (ClassPath.Contains(TEXT("ChooserTable"))) return TEXT("chooser_table");
    if (ClassPath.Contains(TEXT("ProxyTable"))) return TEXT("proxy_table");
    if (ClassPath.Contains(TEXT("IKRigDefinition"))) return TEXT("ik_rig");
    if (ClassPath.Contains(TEXT("IKRetargeter"))) return TEXT("ik_retargeter");
    return FString();
}

static FString OptionalFamily(const FString& Kind)
{
    if (Kind == TEXT("chooser_table")) return TEXT("chooser");
    if (Kind == TEXT("proxy_table")) return TEXT("proxy_table");
    if (Kind == TEXT("ik_rig") || Kind == TEXT("ik_retargeter")) return TEXT("ik_rig");
    return FString();
}

static bool WriteNotifyRows(UAnimSequenceBase* Sequence, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    if (!Sequence)
    {
        return true;
    }
    for (int32 Index = 0; Index < Sequence->Notifies.Num(); ++Index)
    {
        const FAnimNotifyEvent& Event = Sequence->Notifies[Index];
        UAnimNotifyState* NotifyState = Event.NotifyStateClass.Get();
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetNumberField(TEXT("notify_index"), Index);
        Row->SetStringField(TEXT("notify_name"), Event.NotifyName.ToString());
        Row->SetStringField(TEXT("guid"), Event.Guid.ToString(EGuidFormats::DigitsWithHyphensLower));
        Row->SetNumberField(TEXT("trigger_time"), Event.GetTriggerTime());
        Row->SetNumberField(TEXT("end_trigger_time"), Event.GetEndTriggerTime());
        Row->SetNumberField(TEXT("duration"), Event.GetDuration());
        Row->SetNumberField(TEXT("track_index"), Event.TrackIndex);
        Row->SetBoolField(TEXT("branching_point"), Event.IsBranchingPoint());
        Row->SetNumberField(TEXT("trigger_chance"), Event.NotifyTriggerChance);
        Row->SetNumberField(TEXT("trigger_weight_threshold"), Event.TriggerWeightThreshold);
        Row->SetBoolField(TEXT("trigger_on_dedicated_server"), Event.bTriggerOnDedicatedServer);
        Row->SetBoolField(TEXT("trigger_on_follower"), Event.bTriggerOnFollower);
        Row->SetStringField(TEXT("notify_object"), Event.Notify ? Event.Notify->GetPathName() : FString());
        Row->SetStringField(TEXT("notify_class"), Event.Notify ? Event.Notify->GetClass()->GetPathName() : FString());
        Row->SetStringField(TEXT("notify_state_object"), NotifyState ? NotifyState->GetPathName() : FString());
        Row->SetStringField(TEXT("notify_state_class"), NotifyState ? NotifyState->GetClass()->GetPathName() : FString());
        if (!Writers.Notifies.Write(Row))
        {
            return false;
        }
        ++Counts.Notifies;
    }
    return true;
}

static bool WriteSyncMarker(FWriters& Writers, FCounts& Counts, const FString& AssetPath, int32 Index, const FAnimSyncMarker& Marker, const FString& Source)
{
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetNumberField(TEXT("marker_index"), Index);
    Row->SetStringField(TEXT("marker_name"), Marker.MarkerName.ToString());
    Row->SetStringField(TEXT("guid"), Marker.Guid.ToString(EGuidFormats::DigitsWithHyphensLower));
    Row->SetNumberField(TEXT("time"), Marker.Time);
    Row->SetNumberField(TEXT("track_index"), Marker.TrackIndex);
    Row->SetStringField(TEXT("source"), Source);
    if (!Writers.SyncMarkers.Write(Row))
    {
        return false;
    }
    ++Counts.SyncMarkers;
    return true;
}

static bool WriteAnimationAsset(UObject* Object, const FAssetData& Asset, const FString& Kind, FWriters& Writers, FCounts& Counts)
{
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    Row->SetStringField(TEXT("animation_path"), AssetPath);
    Row->SetStringField(TEXT("animation_kind"), Kind);
    Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("skeleton_path"), FString());
    Row->SetNumberField(TEXT("play_length"), 0.0);
    Row->SetBoolField(TEXT("additive"), false);
    Row->SetNumberField(TEXT("notify_count"), 0);
    Row->SetNumberField(TEXT("sync_marker_count"), 0);

    if (UAnimationAsset* Animation = Cast<UAnimationAsset>(Object))
    {
        Row->SetStringField(TEXT("skeleton_path"), Animation->GetSkeleton() ? Animation->GetSkeleton()->GetPathName() : FString());
        Row->SetNumberField(TEXT("play_length"), Animation->GetPlayLength());
        Row->SetBoolField(TEXT("additive"), Animation->IsValidAdditive());
    }
    if (UAnimSequenceBase* Sequence = Cast<UAnimSequenceBase>(Object))
    {
        Row->SetNumberField(TEXT("notify_count"), Sequence->Notifies.Num());
        Row->SetStringField(TEXT("rate_scale"), ExportObjectProperty(Sequence, TEXT("RateScale")));
        Row->SetStringField(TEXT("looping"), ExportObjectProperty(Sequence, TEXT("bLoop")));
    }
    if (UAnimSequence* Sequence = Cast<UAnimSequence>(Object))
    {
        Row->SetNumberField(TEXT("sync_marker_count"), Sequence->AuthoredSyncMarkers.Num());
        Row->SetBoolField(TEXT("root_motion_enabled"), Sequence->bEnableRootMotion);
    }
    if (UAnimMontage* Montage = Cast<UAnimMontage>(Object))
    {
        Row->SetNumberField(TEXT("montage_section_count"), Montage->CompositeSections.Num());
        Row->SetNumberField(TEXT("montage_slot_count"), Montage->SlotAnimTracks.Num());
        Row->SetNumberField(TEXT("sync_marker_count"), Montage->MarkerData.AuthoredSyncMarkers.Num());
    }
    if (UBlendSpace* BlendSpace = Cast<UBlendSpace>(Object))
    {
        Row->SetNumberField(TEXT("blend_sample_count"), BlendSpace->GetNumberOfBlendSamples());
        Row->SetNumberField(TEXT("sync_marker_count"), BlendSpace->GetAuthoredSyncMarkers().Num());
    }

    if (!Writers.Assets.Write(Row))
    {
        return false;
    }
    ++Counts.Assets;
    return true;
}

static bool ScanCoreAnimation(UObject* Object, const FAssetData& Asset, const FString& Kind, FWriters& Writers, FCounts& Counts)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    if (!WriteAnimationAsset(Object, Asset, Kind, Writers, Counts)) return false;
    if (!WriteProperties(Object, AssetPath, Kind, Writers, Counts)) return false;
    WriteReferences(Object, AssetPath, Kind, Writers, Counts);

    if (UAnimSequenceBase* Sequence = Cast<UAnimSequenceBase>(Object))
    {
        if (!WriteNotifyRows(Sequence, AssetPath, Writers, Counts)) return false;
    }
    if (UAnimSequence* Sequence = Cast<UAnimSequence>(Object))
    {
        for (int32 Index = 0; Index < Sequence->AuthoredSyncMarkers.Num(); ++Index)
        {
            if (!WriteSyncMarker(Writers, Counts, AssetPath, Index, Sequence->AuthoredSyncMarkers[Index], TEXT("sequence"))) return false;
        }
    }
    if (UAnimMontage* Montage = Cast<UAnimMontage>(Object))
    {
        for (int32 Index = 0; Index < Montage->CompositeSections.Num(); ++Index)
        {
            const FCompositeSection& Section = Montage->CompositeSections[Index];
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("montage_path"), AssetPath);
            Row->SetNumberField(TEXT("section_index"), Index);
            Row->SetStringField(TEXT("section_name"), Section.SectionName.ToString());
            Row->SetStringField(TEXT("next_section_name"), Section.NextSectionName.ToString());
            Row->SetNumberField(TEXT("start_time"), Section.GetTime());
            if (!Writers.MontageSections.Write(Row)) return false;
            ++Counts.MontageSections;
        }
        for (int32 SlotIndex = 0; SlotIndex < Montage->SlotAnimTracks.Num(); ++SlotIndex)
        {
            const FSlotAnimationTrack& Slot = Montage->SlotAnimTracks[SlotIndex];
            for (int32 SegmentIndex = 0; SegmentIndex < Slot.AnimTrack.AnimSegments.Num(); ++SegmentIndex)
            {
                const FAnimSegment& Segment = Slot.AnimTrack.AnimSegments[SegmentIndex];
                const UAnimSequenceBase* Reference = Segment.GetAnimReference().Get();
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("asset_path"), AssetPath);
                Row->SetStringField(TEXT("asset_kind"), TEXT("anim_montage"));
                Row->SetNumberField(TEXT("slot_index"), SlotIndex);
                Row->SetStringField(TEXT("slot_name"), Slot.SlotName.ToString());
                Row->SetNumberField(TEXT("segment_index"), SegmentIndex);
                Row->SetStringField(TEXT("animation_path"), Reference ? Reference->GetPathName() : FString());
                Row->SetStringField(TEXT("animation_class"), Reference ? Reference->GetClass()->GetPathName() : FString());
                Row->SetNumberField(TEXT("start_pos"), Segment.StartPos);
                Row->SetNumberField(TEXT("anim_start_time"), Segment.AnimStartTime);
                Row->SetNumberField(TEXT("anim_end_time"), Segment.AnimEndTime);
                Row->SetNumberField(TEXT("anim_play_rate"), Segment.AnimPlayRate);
                Row->SetNumberField(TEXT("looping_count"), Segment.LoopingCount);
                if (!Writers.Segments.Write(Row)) return false;
                ++Counts.Segments;
            }
        }
        for (int32 Index = 0; Index < Montage->MarkerData.AuthoredSyncMarkers.Num(); ++Index)
        {
            if (!WriteSyncMarker(Writers, Counts, AssetPath, Index, Montage->MarkerData.AuthoredSyncMarkers[Index], TEXT("montage"))) return false;
        }
    }
    if (UBlendSpace* BlendSpace = Cast<UBlendSpace>(Object))
    {
        for (int32 AxisIndex = 0; AxisIndex < 3; ++AxisIndex)
        {
            const FBlendParameter& Axis = BlendSpace->GetBlendParameter(AxisIndex);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("blend_space_path"), AssetPath);
            Row->SetNumberField(TEXT("axis_index"), AxisIndex);
            Row->SetStringField(TEXT("display_name"), Axis.DisplayName);
            Row->SetNumberField(TEXT("min"), Axis.Min);
            Row->SetNumberField(TEXT("max"), Axis.Max);
            Row->SetNumberField(TEXT("grid_divisions"), Axis.GridNum);
            Row->SetBoolField(TEXT("snap_to_grid"), Axis.bSnapToGrid);
            Row->SetBoolField(TEXT("wrap_input"), Axis.bWrapInput);
            if (!Writers.BlendSpaceAxes.Write(Row)) return false;
            ++Counts.BlendSpaceAxes;
        }
        const TArray<FBlendSample>& Samples = BlendSpace->GetBlendSamples();
        for (int32 Index = 0; Index < Samples.Num(); ++Index)
        {
            const FBlendSample& Sample = Samples[Index];
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("blend_space_path"), AssetPath);
            Row->SetNumberField(TEXT("sample_index"), Index);
            Row->SetStringField(TEXT("animation_path"), Sample.Animation ? Sample.Animation->GetPathName() : FString());
            Row->SetNumberField(TEXT("x"), Sample.SampleValue.X);
            Row->SetNumberField(TEXT("y"), Sample.SampleValue.Y);
            Row->SetNumberField(TEXT("z"), Sample.SampleValue.Z);
            Row->SetNumberField(TEXT("rate_scale"), Sample.RateScale);
            Row->SetBoolField(TEXT("mirror"), Sample.bMirror);
            Row->SetBoolField(TEXT("single_frame"), Sample.bUseSingleFrameForBlending);
            Row->SetNumberField(TEXT("single_frame_index"), Sample.FrameIndexToSample);
            if (!Writers.BlendSpaceSamples.Write(Row)) return false;
            ++Counts.BlendSpaceSamples;
        }
        int32 MarkerIndex = 0;
        for (const FAnimSyncMarker& Marker : BlendSpace->GetAuthoredSyncMarkers())
        {
            if (!WriteSyncMarker(Writers, Counts, AssetPath, MarkerIndex++, Marker, TEXT("blend_space"))) return false;
        }
    }
    return true;
}

static bool ScanSkeleton(USkeleton* Skeleton, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    if (!Skeleton)
    {
        return true;
    }
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    if (!WriteAnimationAsset(Skeleton, Asset, TEXT("skeleton"), Writers, Counts)) return false;
    if (!WriteProperties(Skeleton, AssetPath, TEXT("skeleton"), Writers, Counts)) return false;
    WriteReferences(Skeleton, AssetPath, TEXT("skeleton"), Writers, Counts);

    const FReferenceSkeleton& Ref = Skeleton->GetReferenceSkeleton();
    TArray<FName> CurveNames;
    Skeleton->GetCurveMetaDataNames(CurveNames);
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("skeleton_path"), AssetPath);
    Summary->SetNumberField(TEXT("bone_count"), Ref.GetNum());
    Summary->SetNumberField(TEXT("raw_bone_count"), Ref.GetRawBoneNum());
    Summary->SetNumberField(TEXT("socket_count"), Skeleton->Sockets.Num());
    Summary->SetNumberField(TEXT("virtual_bone_count"), Skeleton->GetVirtualBones().Num());
    Summary->SetNumberField(TEXT("curve_metadata_count"), CurveNames.Num());
    Summary->SetArrayField(TEXT("curve_names"), NamesJson(CurveNames));
    Summary->SetArrayField(TEXT("animation_notify_names"), NamesJson(Skeleton->AnimationNotifies));
    Summary->SetArrayField(TEXT("sync_marker_names"), NamesJson(Skeleton->GetExistingMarkerNames()));
    if (!Writers.Skeletons.Write(Summary)) return false;
    ++Counts.Skeletons;

    const TArray<FTransform>& RefPose = Ref.GetRefBonePose();
    for (int32 BoneIndex = 0; BoneIndex < Ref.GetNum(); ++BoneIndex)
    {
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("skeleton_path"), AssetPath);
        Row->SetNumberField(TEXT("bone_index"), BoneIndex);
        Row->SetStringField(TEXT("bone_name"), Ref.GetBoneName(BoneIndex).ToString());
        Row->SetNumberField(TEXT("parent_index"), Ref.GetParentIndex(BoneIndex));
        if (RefPose.IsValidIndex(BoneIndex))
        {
            Row->SetObjectField(TEXT("local_ref_transform"), TransformJson(RefPose[BoneIndex]));
        }
        if (!Writers.SkeletonBones.Write(Row)) return false;
        ++Counts.SkeletonBones;
    }
    for (int32 SocketIndex = 0; SocketIndex < Skeleton->Sockets.Num(); ++SocketIndex)
    {
        const USkeletalMeshSocket* Socket = Skeleton->Sockets[SocketIndex];
        if (!Socket)
        {
            continue;
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("skeleton_path"), AssetPath);
        Row->SetNumberField(TEXT("socket_index"), SocketIndex);
        Row->SetStringField(TEXT("socket_path"), Socket->GetPathName());
        Row->SetStringField(TEXT("socket_name"), Socket->SocketName.ToString());
        Row->SetStringField(TEXT("bone_name"), Socket->BoneName.ToString());
        Row->SetBoolField(TEXT("force_always_animated"), Socket->bForceAlwaysAnimated);
        Row->SetObjectField(TEXT("local_transform"), TransformJson(Socket->GetSocketLocalTransform()));
        if (!Writers.SkeletonSockets.Write(Row)) return false;
        ++Counts.SkeletonSockets;
    }
    return true;
}

static bool WritePoseSearchDatabase(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    UObject* Schema = GetObjectProperty(Object, TEXT("Schema"));
    UObject* PreviewMesh = GetObjectProperty(Object, TEXT("PreviewMesh"));
    Row->SetStringField(TEXT("database_path"), AssetPath);
    Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Row->SetStringField(TEXT("schema_path"), Schema ? Schema->GetPathName() : FString());
    Row->SetStringField(TEXT("preview_mesh_path"), PreviewMesh ? PreviewMesh->GetPathName() : FString());
    Row->SetStringField(TEXT("search_mode"), ExportObjectProperty(Object, TEXT("PoseSearchMode")));
    Row->SetStringField(TEXT("tags"), ExportObjectProperty(Object, TEXT("Tags")));

    int32 AssetCount = 0;
    if (FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("DatabaseAnimationAssets"))))
    {
        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        AssetCount = Helper.Num();
        FStructProperty* StructProperty = CastField<FStructProperty>(ArrayProperty->Inner);
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Element = Helper.GetRawPtr(Index);
            UObject* AnimAsset = StructProperty ? GetStructObjectField(StructProperty->Struct, Element, TEXT("AnimAsset")) : nullptr;
            bool bTruncated = false;
            const FString Raw = ExportProperty(ArrayProperty->Inner, Element, Object, bTruncated);
            TSharedRef<FJsonObject> AssetRow = MakeShared<FJsonObject>();
            AssetRow->SetStringField(TEXT("database_path"), AssetPath);
            AssetRow->SetNumberField(TEXT("asset_index"), Index);
            AssetRow->SetStringField(TEXT("animation_path"), AnimAsset ? AnimAsset->GetPathName() : FString());
            AssetRow->SetStringField(TEXT("animation_class"), AnimAsset ? AnimAsset->GetClass()->GetPathName() : FString());
            AssetRow->SetStringField(TEXT("raw_value"), Raw);
            AssetRow->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.PoseSearchDatabaseAssets.Write(AssetRow)) return false;
            ++Counts.PoseSearchDatabaseAssets;
        }
    }
    Row->SetNumberField(TEXT("animation_asset_count"), AssetCount);
    if (!Writers.PoseSearchDatabases.Write(Row)) return false;
    ++Counts.PoseSearchDatabases;
    return true;
}

static bool WritePoseSearchSchema(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("schema_path"), AssetPath);
    Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Row->SetStringField(TEXT("sample_rate"), ExportObjectProperty(Object, TEXT("SampleRate")));
    Row->SetStringField(TEXT("number_of_permutations"), ExportObjectProperty(Object, TEXT("NumberOfPermutations")));
    Row->SetStringField(TEXT("permutations_sample_rate"), ExportObjectProperty(Object, TEXT("PermutationsSampleRate")));
    Row->SetStringField(TEXT("permutations_time_offset"), ExportObjectProperty(Object, TEXT("PermutationsTimeOffset")));
    Row->SetStringField(TEXT("data_preprocessor"), ExportObjectProperty(Object, TEXT("DataPreprocessor")));

    int32 ChannelCount = 0;
    if (FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("Channels"))))
    {
        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        const FObjectPropertyBase* InnerObject = CastField<FObjectPropertyBase>(ArrayProperty->Inner);
        ChannelCount = Helper.Num();
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            UObject* Channel = InnerObject ? InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index)) : nullptr;
            TSharedRef<FJsonObject> ChannelRow = MakeShared<FJsonObject>();
            ChannelRow->SetStringField(TEXT("schema_path"), AssetPath);
            ChannelRow->SetNumberField(TEXT("channel_index"), Index);
            ChannelRow->SetStringField(TEXT("channel_path"), Channel ? Channel->GetPathName() : FString());
            ChannelRow->SetStringField(TEXT("channel_class"), Channel ? Channel->GetClass()->GetPathName() : FString());
            if (!Writers.PoseSearchChannels.Write(ChannelRow)) return false;
            ++Counts.PoseSearchChannels;
            if (Channel)
            {
                if (!WriteProperties(Channel, AssetPath, TEXT("pose_search_channel"), Writers, Counts)) return false;
                WriteReferences(Channel, AssetPath, TEXT("pose_search_channel"), Writers, Counts);
            }
        }
    }

    int32 SkeletonCount = 0;
    if (FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("Skeletons"))))
    {
        const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
        FStructProperty* StructProperty = CastField<FStructProperty>(ArrayProperty->Inner);
        SkeletonCount = Helper.Num();
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Element = Helper.GetRawPtr(Index);
            UObject* Skeleton = StructProperty ? GetStructObjectField(StructProperty->Struct, Element, TEXT("Skeleton")) : nullptr;
            UObject* Mirror = StructProperty ? GetStructObjectField(StructProperty->Struct, Element, TEXT("MirrorDataTable")) : nullptr;
            bool bTruncated = false;
            const FString Raw = ExportProperty(ArrayProperty->Inner, Element, Object, bTruncated);
            TSharedRef<FJsonObject> SkeletonRow = MakeShared<FJsonObject>();
            SkeletonRow->SetStringField(TEXT("schema_path"), AssetPath);
            SkeletonRow->SetNumberField(TEXT("role_index"), Index);
            SkeletonRow->SetStringField(TEXT("role"), StructProperty ? ExportStructField(StructProperty->Struct, Element, TEXT("Role"), Object) : FString());
            SkeletonRow->SetStringField(TEXT("skeleton_path"), Skeleton ? Skeleton->GetPathName() : FString());
            SkeletonRow->SetStringField(TEXT("mirror_data_table_path"), Mirror ? Mirror->GetPathName() : FString());
            SkeletonRow->SetStringField(TEXT("raw_value"), Raw);
            SkeletonRow->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.PoseSearchSchemaSkeletons.Write(SkeletonRow)) return false;
            ++Counts.PoseSearchSchemaSkeletons;
        }
    }
    Row->SetNumberField(TEXT("channel_count"), ChannelCount);
    Row->SetNumberField(TEXT("skeleton_role_count"), SkeletonCount);
    if (!Writers.PoseSearchSchemas.Write(Row)) return false;
    ++Counts.PoseSearchSchemas;
    return true;
}

static bool SaveManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), AnimationSchemaVersion);
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolAnimation"));
    Root->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
    C->SetNumberField(TEXT("animation_assets"), Counts.Assets);
    C->SetNumberField(TEXT("animation_notifies"), Counts.Notifies);
    C->SetNumberField(TEXT("animation_sync_markers"), Counts.SyncMarkers);
    C->SetNumberField(TEXT("montage_sections"), Counts.MontageSections);
    C->SetNumberField(TEXT("animation_segments"), Counts.Segments);
    C->SetNumberField(TEXT("blend_space_axes"), Counts.BlendSpaceAxes);
    C->SetNumberField(TEXT("blend_space_samples"), Counts.BlendSpaceSamples);
    C->SetNumberField(TEXT("skeletons"), Counts.Skeletons);
    C->SetNumberField(TEXT("skeleton_bones"), Counts.SkeletonBones);
    C->SetNumberField(TEXT("skeleton_sockets"), Counts.SkeletonSockets);
    C->SetNumberField(TEXT("pose_search_databases"), Counts.PoseSearchDatabases);
    C->SetNumberField(TEXT("pose_search_database_assets"), Counts.PoseSearchDatabaseAssets);
    C->SetNumberField(TEXT("pose_search_schemas"), Counts.PoseSearchSchemas);
    C->SetNumberField(TEXT("pose_search_channels"), Counts.PoseSearchChannels);
    C->SetNumberField(TEXT("pose_search_schema_skeletons"), Counts.PoseSearchSchemaSkeletons);
    C->SetNumberField(TEXT("animation_optional_assets"), Counts.OptionalAssets);
    C->SetNumberField(TEXT("animation_properties"), Counts.Properties);
    C->SetNumberField(TEXT("animation_references"), Counts.References);
    Root->SetObjectField(TEXT("counts"), C);

    TArray<TSharedPtr<FJsonValue>> Files;
    static const TCHAR* Names[] = {
        TEXT("animation_assets.jsonl"), TEXT("animation_notifies.jsonl"), TEXT("animation_sync_markers.jsonl"),
        TEXT("montage_sections.jsonl"), TEXT("animation_segments.jsonl"), TEXT("blend_space_axes.jsonl"), TEXT("blend_space_samples.jsonl"),
        TEXT("skeletons.jsonl"), TEXT("skeleton_bones.jsonl"), TEXT("skeleton_sockets.jsonl"),
        TEXT("pose_search_databases.jsonl"), TEXT("pose_search_database_assets.jsonl"), TEXT("pose_search_schemas.jsonl"),
        TEXT("pose_search_channels.jsonl"), TEXT("pose_search_schema_skeletons.jsonl"), TEXT("animation_optional_assets.jsonl"),
        TEXT("animation_properties.jsonl"), TEXT("animation_references.jsonl")
    };
    for (const TCHAR* Name : Names)
    {
        Files.Add(MakeShared<FJsonValueString>(Name));
    }
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer))
    {
        return false;
    }
    return FFileHelper::SaveStringToFile(Text, *FPaths::Combine(OutputDir, TEXT("animation_manifest.json")), FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunAnimationScan(FString& OutError)
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
        OutError = TEXT("could not create animation JSONL output files");
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
        const FString Kind = KindForClass(ClassPath);
        if (Kind.IsEmpty())
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
        if (Kind == TEXT("skeleton"))
        {
            if (!ScanSkeleton(Cast<USkeleton>(Object), Asset, Writers, Counts))
            {
                OutError = TEXT("failed while scanning skeleton ") + AssetPath;
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
            continue;
        }
        if (Kind == TEXT("pose_search_database"))
        {
            if (!WriteAnimationAsset(Object, Asset, Kind, Writers, Counts) ||
                !WriteProperties(Object, AssetPath, Kind, Writers, Counts) ||
                !WritePoseSearchDatabase(Object, Asset, Writers, Counts))
            {
                OutError = TEXT("failed while scanning Pose Search database ") + AssetPath;
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
            WriteReferences(Object, AssetPath, Kind, Writers, Counts);
            continue;
        }
        if (Kind == TEXT("pose_search_schema"))
        {
            if (!WriteAnimationAsset(Object, Asset, Kind, Writers, Counts) ||
                !WriteProperties(Object, AssetPath, Kind, Writers, Counts) ||
                !WritePoseSearchSchema(Object, Asset, Writers, Counts))
            {
                OutError = TEXT("failed while scanning Pose Search schema ") + AssetPath;
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
            WriteReferences(Object, AssetPath, Kind, Writers, Counts);
            continue;
        }
        const FString Family = OptionalFamily(Kind);
        if (!Family.IsEmpty())
        {
            if (!WriteAnimationAsset(Object, Asset, Kind, Writers, Counts) || !WriteProperties(Object, AssetPath, Kind, Writers, Counts))
            {
                OutError = TEXT("failed while scanning optional animation asset ") + AssetPath;
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
            WriteReferences(Object, AssetPath, Kind, Writers, Counts);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("asset_path"), AssetPath);
            Row->SetStringField(TEXT("asset_kind"), Kind);
            Row->SetStringField(TEXT("family"), Family);
            Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
            if (!Writers.OptionalAssets.Write(Row))
            {
                OutError = TEXT("failed writing optional animation asset ") + AssetPath;
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
            ++Counts.OptionalAssets;
            continue;
        }
        if (!ScanCoreAnimation(Object, Asset, Kind, Writers, Counts))
        {
            OutError = TEXT("failed while scanning animation asset ") + AssetPath;
            SaveManifest(OutputDir, Counts, false, OutError);
            return false;
        }
    }

    if (!SaveManifest(OutputDir, Counts, true, FString()))
    {
        OutError = TEXT("could not write animation_manifest.json");
        return false;
    }
    UE_LOG(LogTemp, Display, TEXT("UnrealAssetToolAnimation: assets=%lld notifies=%lld markers=%lld skeletons=%lld pose_search_databases=%lld pose_search_schemas=%lld"),
        Counts.Assets, Counts.Notifies, Counts.SyncMarkers, Counts.Skeletons, Counts.PoseSearchDatabases, Counts.PoseSearchSchemas);
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
    if (!RunAnimationScan(Error))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolAnimation: %s"), *Error);
    }
}

struct FAnimationScannerBootstrap
{
    FAnimationScannerBootstrap()
    {
        FCoreDelegates::GetOnPostEngineInit().AddStatic(&OnPostEngineInit);
    }
};

static FAnimationScannerBootstrap GAnimationScannerBootstrap;
}
