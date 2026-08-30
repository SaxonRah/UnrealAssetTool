#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Animation/PoseAsset.h"
#include "Animation/Skeleton.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Math/UnrealMathUtility.h"
#include "Misc/CommandLine.h"
#include "Misc/CoreDelegates.h"
#include "Misc/DateTime.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Regex.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolAnimationBreadth
{
static constexpr int32 BreadthSchemaVersion = 1;
static constexpr int32 MaxExportChars = 131072;

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
private:
    TUniquePtr<FArchive> Archive;
};

struct FCounts
{
    int64 PoseAssets = 0, PoseTracks = 0, Poses = 0, PoseTransforms = 0, PoseCurveValues = 0;
    int64 SkeletonSlotGroups = 0, SkeletonSlots = 0;
    int64 ChooserTables = 0, ChooserColumns = 0, ChooserResults = 0, ChooserContext = 0;
    int64 ProxyTables = 0, ProxyEntries = 0, ProxyInheritance = 0;
    int64 IKRigs = 0, IKRigBones = 0, IKRigChains = 0, IKRigGoals = 0, IKRigSolvers = 0;
    int64 IKRetargeters = 0, IKRetargetOps = 0, IKRetargetPoses = 0;
    int64 StructReferences = 0;
};

struct FWriters
{
    FJsonlWriter PoseAssets, PoseTracks, Poses, PoseTransforms, PoseCurveValues;
    FJsonlWriter SkeletonSlotGroups, SkeletonSlots;
    FJsonlWriter ChooserTables, ChooserColumns, ChooserResults, ChooserContext;
    FJsonlWriter ProxyTables, ProxyEntries, ProxyInheritance;
    FJsonlWriter IKRigs, IKRigBones, IKRigChains, IKRigGoals, IKRigSolvers;
    FJsonlWriter IKRetargeters, IKRetargetOps, IKRetargetPoses;
    FJsonlWriter StructReferences;

    bool Open(const FString& OutputDir)
    {
        return PoseAssets.Open(FPaths::Combine(OutputDir, TEXT("pose_assets.jsonl"))) &&
            PoseTracks.Open(FPaths::Combine(OutputDir, TEXT("pose_asset_tracks.jsonl"))) &&
            Poses.Open(FPaths::Combine(OutputDir, TEXT("pose_asset_poses.jsonl"))) &&
            PoseTransforms.Open(FPaths::Combine(OutputDir, TEXT("pose_asset_transforms.jsonl"))) &&
            PoseCurveValues.Open(FPaths::Combine(OutputDir, TEXT("pose_asset_curve_values.jsonl"))) &&
            SkeletonSlotGroups.Open(FPaths::Combine(OutputDir, TEXT("skeleton_slot_groups.jsonl"))) &&
            SkeletonSlots.Open(FPaths::Combine(OutputDir, TEXT("skeleton_slots.jsonl"))) &&
            ChooserTables.Open(FPaths::Combine(OutputDir, TEXT("chooser_tables.jsonl"))) &&
            ChooserColumns.Open(FPaths::Combine(OutputDir, TEXT("chooser_columns.jsonl"))) &&
            ChooserResults.Open(FPaths::Combine(OutputDir, TEXT("chooser_results.jsonl"))) &&
            ChooserContext.Open(FPaths::Combine(OutputDir, TEXT("chooser_context.jsonl"))) &&
            ProxyTables.Open(FPaths::Combine(OutputDir, TEXT("proxy_tables.jsonl"))) &&
            ProxyEntries.Open(FPaths::Combine(OutputDir, TEXT("proxy_entries.jsonl"))) &&
            ProxyInheritance.Open(FPaths::Combine(OutputDir, TEXT("proxy_table_inheritance.jsonl"))) &&
            IKRigs.Open(FPaths::Combine(OutputDir, TEXT("ik_rigs.jsonl"))) &&
            IKRigBones.Open(FPaths::Combine(OutputDir, TEXT("ik_rig_bones.jsonl"))) &&
            IKRigChains.Open(FPaths::Combine(OutputDir, TEXT("ik_rig_chains.jsonl"))) &&
            IKRigGoals.Open(FPaths::Combine(OutputDir, TEXT("ik_rig_goals.jsonl"))) &&
            IKRigSolvers.Open(FPaths::Combine(OutputDir, TEXT("ik_rig_solvers.jsonl"))) &&
            IKRetargeters.Open(FPaths::Combine(OutputDir, TEXT("ik_retargeters.jsonl"))) &&
            IKRetargetOps.Open(FPaths::Combine(OutputDir, TEXT("ik_retarget_ops.jsonl"))) &&
            IKRetargetPoses.Open(FPaths::Combine(OutputDir, TEXT("ik_retarget_poses.jsonl"))) &&
            StructReferences.Open(FPaths::Combine(OutputDir, TEXT("animation_struct_references.jsonl")));
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
    FString F = NormalizeAbsolutePath(File), D = NormalizeAbsolutePath(Directory);
    if (!D.EndsWith(TEXT("/"))) D.AppendChar(TEXT('/'));
    return F.StartsWith(D, ESearchCase::IgnoreCase);
}

static FString ExportProperty(const FProperty* Property, const void* ValuePtr, UObject* Owner, bool& bTruncated)
{
    bTruncated = false;
    if (!Property || !ValuePtr) return FString();
    FString Value;
    Property->ExportTextItem_Direct(Value, ValuePtr, nullptr, Owner, PPF_None, nullptr);
    if (Value.Len() > MaxExportChars)
    {
        Value.LeftInline(MaxExportChars, EAllowShrinking::No);
        bTruncated = true;
    }
    return Value;
}

static FString ExportObjectField(UObject* Object, const FName FieldName)
{
    if (!Object) return FString();
    const FProperty* Property = Object->GetClass()->FindPropertyByName(FieldName);
    if (!Property) return FString();
    bool bTruncated = false;
    return ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(Object), Object, bTruncated);
}

static FString ExportStructField(UStruct* Struct, const void* StructValue, const FName FieldName, UObject* Owner)
{
    if (!Struct || !StructValue) return FString();
    const FProperty* Property = Struct->FindPropertyByName(FieldName);
    if (!Property) return FString();
    bool bTruncated = false;
    return ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(StructValue), Owner, bTruncated);
}

static UObject* GetObjectField(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    if (!Struct || !StructValue) return nullptr;
    const FObjectPropertyBase* Property = CastField<FObjectPropertyBase>(Struct->FindPropertyByName(FieldName));
    if (!Property) return nullptr;
    const void* Ptr = Property->ContainerPtrToValuePtr<void>(StructValue);
    return Ptr ? Property->GetObjectPropertyValue(Ptr) : nullptr;
}

static UObject* GetObjectField(UObject* Object, const FName FieldName)
{
    return Object ? GetObjectField(Object->GetClass(), Object, FieldName) : nullptr;
}

static FString GetNameField(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    if (!Struct || !StructValue) return FString();
    const FNameProperty* Property = CastField<FNameProperty>(Struct->FindPropertyByName(FieldName));
    if (!Property) return FString();
    const void* Ptr = Property->ContainerPtrToValuePtr<void>(StructValue);
    return Ptr ? Property->GetPropertyValue(Ptr).ToString() : FString();
}

static FString GetNameField(UObject* Object, const FName FieldName)
{
    return Object ? GetNameField(Object->GetClass(), Object, FieldName) : FString();
}

static bool GetBoolField(UObject* Object, const FName FieldName, const bool DefaultValue = false)
{
    if (!Object) return DefaultValue;
    const FBoolProperty* Property = CastField<FBoolProperty>(Object->GetClass()->FindPropertyByName(FieldName));
    if (!Property) return DefaultValue;
    return Property->GetPropertyValue_InContainer(Object);
}

static int64 GetIntegerField(UObject* Object, const FName FieldName, const int64 DefaultValue = 0)
{
    if (!Object) return DefaultValue;
    const FNumericProperty* Property = CastField<FNumericProperty>(Object->GetClass()->FindPropertyByName(FieldName));
    if (!Property || !Property->IsInteger()) return DefaultValue;
    const void* Ptr = Property->ContainerPtrToValuePtr<void>(Object);
    return Ptr ? Property->GetSignedIntPropertyValue(Ptr) : DefaultValue;
}

static int32 GetArrayCount(UObject* Object, const FName FieldName)
{
    if (!Object) return 0;
    FArrayProperty* Property = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(FieldName));
    if (!Property) return 0;
    const void* Ptr = Property->ContainerPtrToValuePtr<void>(Object);
    if (!Ptr) return 0;
    FScriptArrayHelper Helper(Property, Ptr);
    return Helper.Num();
}

static TArray<FName> ReadNameArray(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    TArray<FName> Out;
    if (!Struct || !StructValue) return Out;
    FArrayProperty* Array = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
    const FNameProperty* Inner = Array ? CastField<FNameProperty>(Array->Inner) : nullptr;
    if (!Array || !Inner) return Out;
    const void* Ptr = Array->ContainerPtrToValuePtr<void>(StructValue);
    if (!Ptr) return Out;
    FScriptArrayHelper Helper(Array, Ptr);
    Out.Reserve(Helper.Num());
    for (int32 Index = 0; Index < Helper.Num(); ++Index) Out.Add(Inner->GetPropertyValue(Helper.GetRawPtr(Index)));
    return Out;
}

static TArray<int32> ReadIntArray(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    TArray<int32> Out;
    if (!Struct || !StructValue) return Out;
    FArrayProperty* Array = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
    const FNumericProperty* Inner = Array ? CastField<FNumericProperty>(Array->Inner) : nullptr;
    if (!Array || !Inner || !Inner->IsInteger()) return Out;
    const void* Ptr = Array->ContainerPtrToValuePtr<void>(StructValue);
    if (!Ptr) return Out;
    FScriptArrayHelper Helper(Array, Ptr);
    Out.Reserve(Helper.Num());
    for (int32 Index = 0; Index < Helper.Num(); ++Index) Out.Add((int32)Inner->GetSignedIntPropertyValue(Helper.GetRawPtr(Index)));
    return Out;
}

static TArray<FTransform> ReadTransformArray(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    TArray<FTransform> Out;
    if (!Struct || !StructValue) return Out;
    FArrayProperty* Array = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
    const FStructProperty* Inner = Array ? CastField<FStructProperty>(Array->Inner) : nullptr;
    if (!Array || !Inner || Inner->Struct != TBaseStructure<FTransform>::Get()) return Out;
    const void* Ptr = Array->ContainerPtrToValuePtr<void>(StructValue);
    if (!Ptr) return Out;
    FScriptArrayHelper Helper(Array, Ptr);
    Out.Reserve(Helper.Num());
    for (int32 Index = 0; Index < Helper.Num(); ++Index) Out.Add(*reinterpret_cast<const FTransform*>(Helper.GetRawPtr(Index)));
    return Out;
}

static FString GetNestedBoneName(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    if (!Struct || !StructValue) return FString();
    const FStructProperty* Property = CastField<FStructProperty>(Struct->FindPropertyByName(FieldName));
    if (!Property) return FString();
    const void* Ptr = Property->ContainerPtrToValuePtr<void>(StructValue);
    return GetNameField(Property->Struct, Ptr, TEXT("BoneName"));
}

static FString StructTypeFromExport(const FString& Value)
{
    FString Trimmed = Value.TrimStartAndEnd();
    const int32 Open = Trimmed.Find(TEXT("("));
    if (Open > 0 && Trimmed.StartsWith(TEXT("/Script/"))) return Trimmed.Left(Open);
    return FString();
}

static void SetFiniteNumber(const TSharedRef<FJsonObject>& Row, const TCHAR* Name, double Value)
{
    if (FMath::IsFinite(Value)) Row->SetNumberField(Name, Value);
    else Row->SetField(Name, MakeShared<FJsonValueNull>());
}

static void SetTransform(const TSharedRef<FJsonObject>& Row, const FTransform& Transform)
{
    const FVector T = Transform.GetTranslation();
    const FQuat R = Transform.GetRotation();
    const FVector S = Transform.GetScale3D();
    SetFiniteNumber(Row, TEXT("translation_x"), T.X); SetFiniteNumber(Row, TEXT("translation_y"), T.Y); SetFiniteNumber(Row, TEXT("translation_z"), T.Z);
    SetFiniteNumber(Row, TEXT("rotation_x"), R.X); SetFiniteNumber(Row, TEXT("rotation_y"), R.Y); SetFiniteNumber(Row, TEXT("rotation_z"), R.Z); SetFiniteNumber(Row, TEXT("rotation_w"), R.W);
    SetFiniteNumber(Row, TEXT("scale_x"), S.X); SetFiniteNumber(Row, TEXT("scale_y"), S.Y); SetFiniteNumber(Row, TEXT("scale_z"), S.Z);
}

static bool EmitExportReferences(const FString& OwnerPath, const FString& SourceKind, int32 SourceIndex, const FString& RawValue, FWriters& Writers, FCounts& Counts)
{
    static const FRegexPattern Pattern(TEXT("(/Script/[A-Za-z0-9_./]+)'([^']+)'"));
    FRegexMatcher Matcher(Pattern, RawValue);
    TSet<FString> Seen;
    while (Matcher.FindNext())
    {
        const FString TargetClass = Matcher.GetCaptureGroup(1);
        const FString TargetPath = Matcher.GetCaptureGroup(2);
        const FString Key = TargetClass + TEXT("\x1f") + TargetPath;
        if (TargetPath.IsEmpty() || Seen.Contains(Key)) continue;
        Seen.Add(Key);
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("owner_path"), OwnerPath);
        Row->SetStringField(TEXT("source_kind"), SourceKind);
        Row->SetNumberField(TEXT("source_index"), SourceIndex);
        Row->SetStringField(TEXT("reference_kind"), TEXT("export_text_object"));
        Row->SetStringField(TEXT("target_path"), TargetPath);
        Row->SetStringField(TEXT("target_class"), TargetClass);
        if (!Writers.StructReferences.Write(Row)) return false;
        ++Counts.StructReferences;
    }
    return true;
}

static bool WriteInstancedStructArray(UObject* Object, const FString& AssetPath, const FName PropertyName, const FString& SourceKind, FJsonlWriter& Writer, int64& Count, FWriters& Writers, FCounts& Counts, const TArray<bool>* DisabledRows = nullptr)
{
    FArrayProperty* Array = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(PropertyName));
    if (!Array) return true;
    const void* Ptr = Array->ContainerPtrToValuePtr<void>(Object);
    if (!Ptr) return true;
    FScriptArrayHelper Helper(Array, Ptr);
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        bool bTruncated = false;
        const FString Raw = ExportProperty(Array->Inner, Helper.GetRawPtr(Index), Object, bTruncated);
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetNumberField(TEXT("index"), Index);
        Row->SetStringField(TEXT("struct_type"), StructTypeFromExport(Raw));
        Row->SetStringField(TEXT("raw_value"), Raw);
        Row->SetBoolField(TEXT("truncated"), bTruncated);
        if (DisabledRows && DisabledRows->IsValidIndex(Index)) Row->SetBoolField(TEXT("disabled"), (*DisabledRows)[Index]);
        if (!Writer.Write(Row)) return false;
        ++Count;
        if (!EmitExportReferences(AssetPath, SourceKind, Index, Raw, Writers, Counts)) return false;
    }
    return true;
}

static TArray<bool> ReadBoolArray(UObject* Object, const FName FieldName)
{
    TArray<bool> Out;
    FArrayProperty* Array = Object ? CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(FieldName)) : nullptr;
    const FBoolProperty* Inner = Array ? CastField<FBoolProperty>(Array->Inner) : nullptr;
    if (!Array || !Inner) return Out;
    const void* Ptr = Array->ContainerPtrToValuePtr<void>(Object);
    if (!Ptr) return Out;
    FScriptArrayHelper Helper(Array, Ptr);
    Out.Reserve(Helper.Num());
    for (int32 Index = 0; Index < Helper.Num(); ++Index) Out.Add(Inner->GetPropertyValue(Helper.GetRawPtr(Index)));
    return Out;
}

static bool ScanPoseAsset(UPoseAsset* Pose, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    if (!Pose) return true;
    const FString Path = Asset.GetSoftObjectPath().ToString();
    TArray<FName> TrackNames;
    if (const FStructProperty* ContainerProperty = CastField<FStructProperty>(Pose->GetClass()->FindPropertyByName(TEXT("PoseContainer"))))
    {
        const void* Container = ContainerProperty->ContainerPtrToValuePtr<void>(Pose);
        TrackNames = ReadNameArray(ContainerProperty->Struct, Container, TEXT("Tracks"));
    }
    const TArray<FName>& PoseNames = Pose->GetPoseFNames();
    const TArray<FName> CurveNames = Pose->GetCurveFNames();
    UObject* SourceAnimation = GetObjectField(Pose, TEXT("SourceAnimation"));

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("pose_asset_path"), Path);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("skeleton_path"), Pose->GetSkeleton() ? Pose->GetSkeleton()->GetPathName() : FString());
    Summary->SetStringField(TEXT("source_animation_path"), SourceAnimation ? SourceAnimation->GetPathName() : FString());
    Summary->SetBoolField(TEXT("additive"), GetBoolField(Pose, TEXT("bAdditivePose"), false));
    Summary->SetNumberField(TEXT("base_pose_index"), GetIntegerField(Pose, TEXT("BasePoseIndex"), -1));
    Summary->SetNumberField(TEXT("pose_count"), Pose->GetNumPoses());
    Summary->SetNumberField(TEXT("track_count"), Pose->GetNumTracks());
    Summary->SetNumberField(TEXT("curve_count"), Pose->GetNumCurves());
    if (!Writers.PoseAssets.Write(Summary)) return false;
    ++Counts.PoseAssets;

    for (int32 TrackIndex = 0; TrackIndex < TrackNames.Num(); ++TrackIndex)
    {
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("pose_asset_path"), Path);
        Row->SetNumberField(TEXT("track_index"), TrackIndex);
        Row->SetStringField(TEXT("track_name"), TrackNames[TrackIndex].ToString());
        if (!Writers.PoseTracks.Write(Row)) return false;
        ++Counts.PoseTracks;
    }

    for (int32 PoseIndex = 0; PoseIndex < Pose->GetNumPoses(); ++PoseIndex)
    {
        const FString PoseName = PoseNames.IsValidIndex(PoseIndex) ? PoseNames[PoseIndex].ToString() : FString();
        const TArray<FTransform>& RawPose = Pose->GetRawPose(PoseIndex);
        const TArray<FTransform>& FullPose = Pose->GetFullPose(PoseIndex);
        const TArray<float>& RawCurves = Pose->GetRawCurveValues(PoseIndex);
        const TArray<float>& FullCurves = Pose->GetFullCurveValues(PoseIndex);
        TSharedRef<FJsonObject> PoseRow = MakeShared<FJsonObject>();
        PoseRow->SetStringField(TEXT("pose_asset_path"), Path);
        PoseRow->SetNumberField(TEXT("pose_index"), PoseIndex);
        PoseRow->SetStringField(TEXT("pose_name"), PoseName);
        PoseRow->SetNumberField(TEXT("raw_transform_count"), RawPose.Num());
        PoseRow->SetNumberField(TEXT("full_transform_count"), FullPose.Num());
        PoseRow->SetNumberField(TEXT("raw_curve_count"), RawCurves.Num());
        PoseRow->SetNumberField(TEXT("full_curve_count"), FullCurves.Num());
        PoseRow->SetBoolField(TEXT("full_pose_matches_track_count"), FullPose.Num() == TrackNames.Num());
        if (!Writers.Poses.Write(PoseRow)) return false;
        ++Counts.Poses;

        for (int32 TrackIndex = 0; TrackIndex < FullPose.Num(); ++TrackIndex)
        {
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("pose_asset_path"), Path);
            Row->SetNumberField(TEXT("pose_index"), PoseIndex);
            Row->SetStringField(TEXT("pose_name"), PoseName);
            Row->SetNumberField(TEXT("track_index"), TrackIndex);
            Row->SetStringField(TEXT("track_name"), TrackNames.IsValidIndex(TrackIndex) ? TrackNames[TrackIndex].ToString() : FString());
            SetTransform(Row, FullPose[TrackIndex]);
            if (!Writers.PoseTransforms.Write(Row)) return false;
            ++Counts.PoseTransforms;
        }
        const int32 CurveCount = FMath::Max(RawCurves.Num(), FullCurves.Num());
        for (int32 CurveIndex = 0; CurveIndex < CurveCount; ++CurveIndex)
        {
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("pose_asset_path"), Path);
            Row->SetNumberField(TEXT("pose_index"), PoseIndex);
            Row->SetStringField(TEXT("pose_name"), PoseName);
            Row->SetNumberField(TEXT("curve_index"), CurveIndex);
            Row->SetStringField(TEXT("curve_name"), CurveNames.IsValidIndex(CurveIndex) ? CurveNames[CurveIndex].ToString() : FString());
            if (RawCurves.IsValidIndex(CurveIndex)) SetFiniteNumber(Row, TEXT("raw_value"), RawCurves[CurveIndex]); else Row->SetField(TEXT("raw_value"), MakeShared<FJsonValueNull>());
            if (FullCurves.IsValidIndex(CurveIndex)) SetFiniteNumber(Row, TEXT("full_value"), FullCurves[CurveIndex]); else Row->SetField(TEXT("full_value"), MakeShared<FJsonValueNull>());
            if (!Writers.PoseCurveValues.Write(Row)) return false;
            ++Counts.PoseCurveValues;
        }
    }
    return true;
}

static bool ScanSkeletonSlots(UObject* Skeleton, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    FArrayProperty* Groups = Skeleton ? CastField<FArrayProperty>(Skeleton->GetClass()->FindPropertyByName(TEXT("SlotGroups"))) : nullptr;
    FStructProperty* GroupStruct = Groups ? CastField<FStructProperty>(Groups->Inner) : nullptr;
    if (!Groups || !GroupStruct) return true;
    const void* Ptr = Groups->ContainerPtrToValuePtr<void>(Skeleton);
    if (!Ptr) return true;
    FScriptArrayHelper Helper(Groups, Ptr);
    const FString Path = Asset.GetSoftObjectPath().ToString();
    for (int32 GroupIndex = 0; GroupIndex < Helper.Num(); ++GroupIndex)
    {
        const void* Group = Helper.GetRawPtr(GroupIndex);
        const FString GroupName = GetNameField(GroupStruct->Struct, Group, TEXT("GroupName"));
        const TArray<FName> SlotNames = ReadNameArray(GroupStruct->Struct, Group, TEXT("SlotNames"));
        TSharedRef<FJsonObject> GroupRow = MakeShared<FJsonObject>();
        GroupRow->SetStringField(TEXT("skeleton_path"), Path);
        GroupRow->SetNumberField(TEXT("group_index"), GroupIndex);
        GroupRow->SetStringField(TEXT("group_name"), GroupName.IsEmpty() || GroupName == TEXT("None") ? TEXT("DefaultGroup") : GroupName);
        GroupRow->SetNumberField(TEXT("slot_count"), SlotNames.Num());
        if (!Writers.SkeletonSlotGroups.Write(GroupRow)) return false;
        ++Counts.SkeletonSlotGroups;
        for (int32 SlotIndex = 0; SlotIndex < SlotNames.Num(); ++SlotIndex)
        {
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("skeleton_path"), Path);
            Row->SetNumberField(TEXT("group_index"), GroupIndex);
            Row->SetStringField(TEXT("group_name"), GroupRow->GetStringField(TEXT("group_name")));
            Row->SetNumberField(TEXT("slot_index"), SlotIndex);
            Row->SetStringField(TEXT("slot_name"), SlotNames[SlotIndex].ToString());
            if (!Writers.SkeletonSlots.Write(Row)) return false;
            ++Counts.SkeletonSlots;
        }
    }
    return true;
}

static bool ScanChooser(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    const TArray<bool> Disabled = ReadBoolArray(Object, TEXT("DisabledRows"));
    const int32 Columns = GetArrayCount(Object, TEXT("ColumnsStructs"));
    const int32 Results = GetArrayCount(Object, TEXT("ResultsStructs"));
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("chooser_path"), Path);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetNumberField(TEXT("column_count"), Columns);
    Summary->SetNumberField(TEXT("result_count"), Results);
    int32 DisabledCount = 0; for (const bool bDisabled : Disabled) if (bDisabled) ++DisabledCount;
    Summary->SetNumberField(TEXT("disabled_row_count"), DisabledCount);
    Summary->SetNumberField(TEXT("context_count"), GetArrayCount(Object, TEXT("ContextData")));
    Summary->SetNumberField(TEXT("nested_chooser_count"), GetArrayCount(Object, TEXT("NestedChoosers")));
    Summary->SetStringField(TEXT("result_type"), ExportObjectField(Object, TEXT("ResultType")));
    Summary->SetStringField(TEXT("output_object_type"), ExportObjectField(Object, TEXT("OutputObjectType")));
    const FString Fallback = ExportObjectField(Object, TEXT("FallbackResult"));
    Summary->SetStringField(TEXT("fallback_raw_value"), Fallback);
    if (!Writers.ChooserTables.Write(Summary)) return false;
    ++Counts.ChooserTables;
    if (!EmitExportReferences(Path, TEXT("chooser_fallback"), -1, Fallback, Writers, Counts)) return false;
    if (!WriteInstancedStructArray(Object, Path, TEXT("ColumnsStructs"), TEXT("chooser_column"), Writers.ChooserColumns, Counts.ChooserColumns, Writers, Counts)) return false;
    if (!WriteInstancedStructArray(Object, Path, TEXT("ResultsStructs"), TEXT("chooser_result"), Writers.ChooserResults, Counts.ChooserResults, Writers, Counts, &Disabled)) return false;
    if (!WriteInstancedStructArray(Object, Path, TEXT("ContextData"), TEXT("chooser_context"), Writers.ChooserContext, Counts.ChooserContext, Writers, Counts)) return false;
    return true;
}

static bool ScanProxyTable(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    FArrayProperty* Entries = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("Entries")));
    FStructProperty* EntryStruct = Entries ? CastField<FStructProperty>(Entries->Inner) : nullptr;
    const int32 EntryCount = Entries ? GetArrayCount(Object, TEXT("Entries")) : 0;
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("proxy_table_path"), Path);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetNumberField(TEXT("entry_count"), EntryCount);
    Summary->SetNumberField(TEXT("inherit_table_count"), GetArrayCount(Object, TEXT("InheritEntriesFrom")));
    if (!Writers.ProxyTables.Write(Summary)) return false;
    ++Counts.ProxyTables;

    if (Entries && EntryStruct)
    {
        const void* Ptr = Entries->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(Entries, Ptr);
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Entry = Helper.GetRawPtr(Index);
            UObject* Proxy = GetObjectField(EntryStruct->Struct, Entry, TEXT("Proxy"));
            const FString ValueRaw = ExportStructField(EntryStruct->Struct, Entry, TEXT("ValueStruct"), Object);
            bool bTruncated = false;
            const FString Raw = ExportProperty(Entries->Inner, Entry, Object, bTruncated);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("proxy_table_path"), Path);
            Row->SetNumberField(TEXT("entry_index"), Index);
            Row->SetStringField(TEXT("proxy_path"), Proxy ? Proxy->GetPathName() : FString());
            Row->SetStringField(TEXT("value_struct_type"), StructTypeFromExport(ValueRaw));
            Row->SetStringField(TEXT("value_raw"), ValueRaw);
            Row->SetStringField(TEXT("raw_value"), Raw);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.ProxyEntries.Write(Row)) return false;
            ++Counts.ProxyEntries;
            if (!EmitExportReferences(Path, TEXT("proxy_entry"), Index, Raw, Writers, Counts)) return false;
        }
    }

    FArrayProperty* Inherit = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("InheritEntriesFrom")));
    FObjectPropertyBase* InnerObject = Inherit ? CastField<FObjectPropertyBase>(Inherit->Inner) : nullptr;
    if (Inherit && InnerObject)
    {
        const void* Ptr = Inherit->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(Inherit, Ptr);
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            UObject* Parent = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("proxy_table_path"), Path);
            Row->SetNumberField(TEXT("inherit_index"), Index);
            Row->SetStringField(TEXT("parent_table_path"), Parent ? Parent->GetPathName() : FString());
            if (!Writers.ProxyInheritance.Write(Row)) return false;
            ++Counts.ProxyInheritance;
        }
    }
    return true;
}

static bool ScanIKRig(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    const FStructProperty* SkeletonProperty = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(TEXT("Skeleton")));
    const void* SkeletonValue = SkeletonProperty ? SkeletonProperty->ContainerPtrToValuePtr<void>(Object) : nullptr;
    const TArray<FName> BoneNames = SkeletonProperty ? ReadNameArray(SkeletonProperty->Struct, SkeletonValue, TEXT("BoneNames")) : TArray<FName>();
    const TArray<int32> ParentIndices = SkeletonProperty ? ReadIntArray(SkeletonProperty->Struct, SkeletonValue, TEXT("ParentIndices")) : TArray<int32>();
    const TArray<FTransform> RefPose = SkeletonProperty ? ReadTransformArray(SkeletonProperty->Struct, SkeletonValue, TEXT("RefPoseGlobal")) : TArray<FTransform>();
    const TArray<FName> ExcludedBones = SkeletonProperty ? ReadNameArray(SkeletonProperty->Struct, SkeletonValue, TEXT("ExcludedBones")) : TArray<FName>();
    TSet<FName> ExcludedSet; for (const FName BoneName : ExcludedBones) ExcludedSet.Add(BoneName);
    UObject* RigMesh = SkeletonProperty ? GetObjectField(SkeletonProperty->Struct, SkeletonValue, TEXT("SkeletalMesh")) : nullptr;

    const FStructProperty* RetargetProperty = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(TEXT("RetargetDefinition")));
    const void* RetargetValue = RetargetProperty ? RetargetProperty->ContainerPtrToValuePtr<void>(Object) : nullptr;
    FArrayProperty* Chains = RetargetProperty ? CastField<FArrayProperty>(RetargetProperty->Struct->FindPropertyByName(TEXT("BoneChains"))) : nullptr;
    const int32 ChainCount = Chains && RetargetValue ? FScriptArrayHelper(Chains, Chains->ContainerPtrToValuePtr<void>(RetargetValue)).Num() : 0;

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("ik_rig_path"), Path);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    UObject* PreviewMesh = GetObjectField(Object, TEXT("PreviewSkeletalMesh"));
    Summary->SetStringField(TEXT("preview_mesh_path"), PreviewMesh ? PreviewMesh->GetPathName() : FString());
    Summary->SetStringField(TEXT("skeleton_mesh_path"), RigMesh ? RigMesh->GetPathName() : FString());
    Summary->SetNumberField(TEXT("bone_count"), BoneNames.Num());
    Summary->SetNumberField(TEXT("excluded_bone_count"), ExcludedBones.Num());
    Summary->SetStringField(TEXT("root_bone"), RetargetProperty ? GetNameField(RetargetProperty->Struct, RetargetValue, TEXT("RootBone")) : FString());
    Summary->SetStringField(TEXT("pelvis_bone"), RetargetProperty ? GetNameField(RetargetProperty->Struct, RetargetValue, TEXT("PelvisBone")) : FString());
    Summary->SetNumberField(TEXT("chain_count"), ChainCount);
    Summary->SetNumberField(TEXT("goal_count"), GetArrayCount(Object, TEXT("Goals")));
    Summary->SetNumberField(TEXT("solver_count"), GetArrayCount(Object, TEXT("SolverStack")));
    if (!Writers.IKRigs.Write(Summary)) return false;
    ++Counts.IKRigs;

    for (int32 BoneIndex = 0; BoneIndex < BoneNames.Num(); ++BoneIndex)
    {
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("ik_rig_path"), Path);
        Row->SetNumberField(TEXT("bone_index"), BoneIndex);
        Row->SetStringField(TEXT("bone_name"), BoneNames[BoneIndex].ToString());
        Row->SetNumberField(TEXT("parent_index"), ParentIndices.IsValidIndex(BoneIndex) ? ParentIndices[BoneIndex] : -1);
        Row->SetBoolField(TEXT("excluded"), ExcludedSet.Contains(BoneNames[BoneIndex]));
        if (RefPose.IsValidIndex(BoneIndex)) SetTransform(Row, RefPose[BoneIndex]);
        if (!Writers.IKRigBones.Write(Row)) return false;
        ++Counts.IKRigBones;
    }

    if (Chains && RetargetValue)
    {
        FStructProperty* ChainStruct = CastField<FStructProperty>(Chains->Inner);
        const void* Ptr = Chains->ContainerPtrToValuePtr<void>(RetargetValue);
        FScriptArrayHelper Helper(Chains, Ptr);
        if (ChainStruct)
        {
            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                const void* Chain = Helper.GetRawPtr(Index);
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("ik_rig_path"), Path);
                Row->SetNumberField(TEXT("chain_index"), Index);
                Row->SetStringField(TEXT("chain_name"), GetNameField(ChainStruct->Struct, Chain, TEXT("ChainName")));
                Row->SetStringField(TEXT("start_bone"), GetNestedBoneName(ChainStruct->Struct, Chain, TEXT("StartBone")));
                Row->SetStringField(TEXT("end_bone"), GetNestedBoneName(ChainStruct->Struct, Chain, TEXT("EndBone")));
                Row->SetStringField(TEXT("ik_goal_name"), GetNameField(ChainStruct->Struct, Chain, TEXT("IKGoalName")));
                if (!Writers.IKRigChains.Write(Row)) return false;
                ++Counts.IKRigChains;
            }
        }
    }

    FArrayProperty* Goals = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("Goals")));
    FObjectPropertyBase* GoalObjectProperty = Goals ? CastField<FObjectPropertyBase>(Goals->Inner) : nullptr;
    if (Goals && GoalObjectProperty)
    {
        const void* Ptr = Goals->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper Helper(Goals, Ptr);
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            UObject* Goal = GoalObjectProperty->GetObjectPropertyValue(Helper.GetRawPtr(Index));
            if (!Goal) continue;
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("ik_rig_path"), Path);
            Row->SetNumberField(TEXT("goal_index"), Index);
            Row->SetStringField(TEXT("goal_path"), Goal->GetPathName());
            Row->SetStringField(TEXT("goal_class"), Goal->GetClass()->GetPathName());
            Row->SetStringField(TEXT("goal_name"), GetNameField(Goal, TEXT("GoalName")));
            Row->SetStringField(TEXT("bone_name"), GetNameField(Goal, TEXT("BoneName")));
            Row->SetStringField(TEXT("position_alpha"), ExportObjectField(Goal, TEXT("PositionAlpha")));
            Row->SetStringField(TEXT("rotation_alpha"), ExportObjectField(Goal, TEXT("RotationAlpha")));
            Row->SetBoolField(TEXT("expose_position"), GetBoolField(Goal, TEXT("bExposePosition"), false));
            Row->SetBoolField(TEXT("expose_rotation"), GetBoolField(Goal, TEXT("bExposeRotation"), false));
            if (!Writers.IKRigGoals.Write(Row)) return false;
            ++Counts.IKRigGoals;
        }
    }

    if (!WriteInstancedStructArray(Object, Path, TEXT("SolverStack"), TEXT("ik_rig_solver"), Writers.IKRigSolvers, Counts.IKRigSolvers, Writers, Counts)) return false;
    return true;
}

static bool WriteRetargetPoseMap(UObject* Object, const FString& Path, const FName PropertyName, const FString& Side, FWriters& Writers, FCounts& Counts)
{
    FMapProperty* Map = CastField<FMapProperty>(Object->GetClass()->FindPropertyByName(PropertyName));
    FNameProperty* Key = Map ? CastField<FNameProperty>(Map->KeyProp) : nullptr;
    if (!Map || !Key) return true;
    const void* Ptr = Map->ContainerPtrToValuePtr<void>(Object);
    if (!Ptr) return true;
    FScriptMapHelper Helper(Map, Ptr);
    int32 LogicalIndex = 0;
    for (int32 SparseIndex = 0; SparseIndex < Helper.GetMaxIndex(); ++SparseIndex)
    {
        if (!Helper.IsValidIndex(SparseIndex)) continue;
        const FString PoseName = Key->GetPropertyValue(Helper.GetKeyPtr(SparseIndex)).ToString();
        bool bTruncated = false;
        const FString Raw = ExportProperty(Map->ValueProp, Helper.GetValuePtr(SparseIndex), Object, bTruncated);
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("retargeter_path"), Path);
        Row->SetStringField(TEXT("side"), Side);
        Row->SetNumberField(TEXT("pose_index"), LogicalIndex++);
        Row->SetStringField(TEXT("pose_name"), PoseName);
        Row->SetStringField(TEXT("raw_value"), Raw);
        Row->SetBoolField(TEXT("truncated"), bTruncated);
        if (!Writers.IKRetargetPoses.Write(Row)) return false;
        ++Counts.IKRetargetPoses;
        if (!EmitExportReferences(Path, TEXT("ik_retarget_pose"), LogicalIndex - 1, Raw, Writers, Counts)) return false;
    }
    return true;
}

static bool ScanIKRetargeter(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    UObject* SourceRig = GetObjectField(Object, TEXT("SourceIKRigAsset"));
    UObject* TargetRig = GetObjectField(Object, TEXT("TargetIKRigAsset"));
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("retargeter_path"), Path);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("source_ik_rig_path"), SourceRig ? SourceRig->GetPathName() : FString());
    Summary->SetStringField(TEXT("target_ik_rig_path"), TargetRig ? TargetRig->GetPathName() : FString());
    Summary->SetStringField(TEXT("source_preview_mesh"), ExportObjectField(Object, TEXT("SourcePreviewMesh")));
    Summary->SetStringField(TEXT("target_preview_mesh"), ExportObjectField(Object, TEXT("TargetPreviewMesh")));
    Summary->SetNumberField(TEXT("op_count"), GetArrayCount(Object, TEXT("RetargetOps")));
    Summary->SetNumberField(TEXT("source_pose_count"), 0);
    Summary->SetNumberField(TEXT("target_pose_count"), 0);
    if (!Writers.IKRetargeters.Write(Summary)) return false;
    ++Counts.IKRetargeters;
    if (!WriteInstancedStructArray(Object, Path, TEXT("RetargetOps"), TEXT("ik_retarget_op"), Writers.IKRetargetOps, Counts.IKRetargetOps, Writers, Counts)) return false;
    if (!WriteRetargetPoseMap(Object, Path, TEXT("SourceRetargetPoses"), TEXT("source"), Writers, Counts)) return false;
    if (!WriteRetargetPoseMap(Object, Path, TEXT("TargetRetargetPoses"), TEXT("target"), Writers, Counts)) return false;
    return true;
}

static bool SaveManifest(const FString& OutputDir, const FCounts& C, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), BreadthSchemaVersion);
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolAnimationBreadth"));
    Root->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    TSharedRef<FJsonObject> Counts = MakeShared<FJsonObject>();
#define SET_COUNT(Name, Field) Counts->SetNumberField(TEXT(Name), C.Field)
    SET_COUNT("pose_assets", PoseAssets); SET_COUNT("pose_asset_tracks", PoseTracks); SET_COUNT("pose_asset_poses", Poses); SET_COUNT("pose_asset_transforms", PoseTransforms); SET_COUNT("pose_asset_curve_values", PoseCurveValues);
    SET_COUNT("skeleton_slot_groups", SkeletonSlotGroups); SET_COUNT("skeleton_slots", SkeletonSlots);
    SET_COUNT("chooser_tables", ChooserTables); SET_COUNT("chooser_columns", ChooserColumns); SET_COUNT("chooser_results", ChooserResults); SET_COUNT("chooser_context", ChooserContext);
    SET_COUNT("proxy_tables", ProxyTables); SET_COUNT("proxy_entries", ProxyEntries); SET_COUNT("proxy_table_inheritance", ProxyInheritance);
    SET_COUNT("ik_rigs", IKRigs); SET_COUNT("ik_rig_bones", IKRigBones); SET_COUNT("ik_rig_chains", IKRigChains); SET_COUNT("ik_rig_goals", IKRigGoals); SET_COUNT("ik_rig_solvers", IKRigSolvers);
    SET_COUNT("ik_retargeters", IKRetargeters); SET_COUNT("ik_retarget_ops", IKRetargetOps); SET_COUNT("ik_retarget_poses", IKRetargetPoses);
    SET_COUNT("animation_struct_references", StructReferences);
#undef SET_COUNT
    Root->SetObjectField(TEXT("counts"), Counts);
    static const TCHAR* Names[] = {
        TEXT("pose_assets.jsonl"), TEXT("pose_asset_tracks.jsonl"), TEXT("pose_asset_poses.jsonl"), TEXT("pose_asset_transforms.jsonl"), TEXT("pose_asset_curve_values.jsonl"),
        TEXT("skeleton_slot_groups.jsonl"), TEXT("skeleton_slots.jsonl"),
        TEXT("chooser_tables.jsonl"), TEXT("chooser_columns.jsonl"), TEXT("chooser_results.jsonl"), TEXT("chooser_context.jsonl"),
        TEXT("proxy_tables.jsonl"), TEXT("proxy_entries.jsonl"), TEXT("proxy_table_inheritance.jsonl"),
        TEXT("ik_rigs.jsonl"), TEXT("ik_rig_bones.jsonl"), TEXT("ik_rig_chains.jsonl"), TEXT("ik_rig_goals.jsonl"), TEXT("ik_rig_solvers.jsonl"),
        TEXT("ik_retargeters.jsonl"), TEXT("ik_retarget_ops.jsonl"), TEXT("ik_retarget_poses.jsonl"), TEXT("animation_struct_references.jsonl")
    };
    TArray<TSharedPtr<FJsonValue>> Files;
    for (const TCHAR* Name : Names) Files.Add(MakeShared<FJsonValueString>(Name));
    Root->SetArrayField(TEXT("files"), Files);
    FString Text;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    return FFileHelper::SaveStringToFile(Text, *FPaths::Combine(OutputDir, TEXT("animation_breadth_manifest.json")), FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunBreadthScan(FString& OutError)
{
    FString OutputDir;
    FParse::Value(FCommandLine::Get(), TEXT("Output="), OutputDir);
    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    if (OutputDir.IsEmpty()) OutputDir = FPaths::Combine(ProjectDir, TEXT(".uatool"));
    else if (FPaths::IsRelative(OutputDir)) OutputDir = FPaths::Combine(ProjectDir, OutputDir);
    OutputDir = NormalizeAbsolutePath(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);
    const bool bIncludeEngine = FParse::Param(FCommandLine::Get(), TEXT("IncludeEngine"));
    const bool bIncludeSelf = FParse::Param(FCommandLine::Get(), TEXT("IncludeSelf"));
    FString ToolPluginDir;
    if (const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("UnrealAssetTool")); Plugin.IsValid()) ToolPluginDir = NormalizeAbsolutePath(Plugin->GetBaseDir());

    FWriters Writers; FCounts Counts;
    if (!Writers.Open(OutputDir))
    {
        OutError = TEXT("could not create breadth animation JSONL output files");
        SaveManifest(OutputDir, Counts, false, OutError); return false;
    }
    FAssetRegistryModule& Module = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = Module.Get(); Registry.SearchAllAssets(true);
    TArray<FAssetData> Assets; Registry.GetAllAssets(Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B) { return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString(); });

    for (const FAssetData& Asset : Assets)
    {
        const FString ClassPath = Asset.AssetClassPath.ToString();
        const bool bPose = ClassPath == TEXT("/Script/Engine.PoseAsset");
        const bool bSkeleton = ClassPath == TEXT("/Script/Engine.Skeleton");
        const bool bChooser = ClassPath == TEXT("/Script/Chooser.ChooserTable");
        const bool bProxyTable = ClassPath == TEXT("/Script/ProxyTable.ProxyTable");
        const bool bIKRig = ClassPath == TEXT("/Script/IKRig.IKRigDefinition");
        const bool bRetargeter = ClassPath == TEXT("/Script/IKRig.IKRetargeter");
        if (!bPose && !bSkeleton && !bChooser && !bProxyTable && !bIKRig && !bRetargeter) continue;
        FString PackageFilename;
        const bool bHasDiskPackage = FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &PackageFilename, false);
        if (!bIncludeSelf && bHasDiskPackage && !ToolPluginDir.IsEmpty() && IsInsideDirectory(PackageFilename, ToolPluginDir)) continue;
        if (!bIncludeEngine && (!bHasDiskPackage || !IsInsideDirectory(PackageFilename, ProjectDir))) continue;
        UObject* Object = Asset.GetAsset(); if (!Object) continue;
        bool bOk = true;
        if (bPose) bOk = ScanPoseAsset(Cast<UPoseAsset>(Object), Asset, Writers, Counts);
        else if (bSkeleton) bOk = ScanSkeletonSlots(Object, Asset, Writers, Counts);
        else if (bChooser) bOk = ScanChooser(Object, Asset, Writers, Counts);
        else if (bProxyTable) bOk = ScanProxyTable(Object, Asset, Writers, Counts);
        else if (bIKRig) bOk = ScanIKRig(Object, Asset, Writers, Counts);
        else if (bRetargeter) bOk = ScanIKRetargeter(Object, Asset, Writers, Counts);
        if (!bOk)
        {
            OutError = TEXT("failed breadth animation scan for ") + Asset.GetSoftObjectPath().ToString();
            SaveManifest(OutputDir, Counts, false, OutError); return false;
        }
    }
    if (!SaveManifest(OutputDir, Counts, true, FString())) { OutError = TEXT("could not write animation_breadth_manifest.json"); return false; }
    UE_LOG(LogTemp, Display, TEXT("UnrealAssetToolAnimationBreadth: pose_assets=%lld chooser_tables=%lld proxy_tables=%lld ik_rigs=%lld retargeters=%lld struct_refs=%lld"),
        Counts.PoseAssets, Counts.ChooserTables, Counts.ProxyTables, Counts.IKRigs, Counts.IKRetargeters, Counts.StructReferences);
    return true;
}

static void OnPostEngineInit()
{
    FString RunCommandlet; FParse::Value(FCommandLine::Get(), TEXT("run="), RunCommandlet);
    if (!RunCommandlet.Equals(TEXT("UnrealAssetToolWorld"), ESearchCase::IgnoreCase)) return;
    FString Error; if (!RunBreadthScan(Error)) UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolAnimationBreadth: %s"), *Error);
}

struct FBreadthScannerBootstrap
{
    FBreadthScannerBootstrap() { FCoreDelegates::GetOnPostEngineInit().AddStatic(&OnPostEngineInit); }
};
static FBreadthScannerBootstrap GBreadthScannerBootstrap;
}
