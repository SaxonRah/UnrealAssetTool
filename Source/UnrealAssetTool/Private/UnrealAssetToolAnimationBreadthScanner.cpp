#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Animation/PoseAsset.h"
#include "Animation/Skeleton.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Internationalization/Regex.h"
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

        for (int32 CurveIndex = 0; CurveIndex < FullCurves.Num(); ++CurveIndex)
        {
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("pose_asset_path"), Path);
            Row->SetNumberField(TEXT("pose_index"), PoseIndex);
            Row->SetStringField(TEXT("pose_name"), PoseName);
            Row->SetNumberField(TEXT("curve_index"), CurveIndex);
            Row->SetStringField(TEXT("curve_name"), CurveNames.IsValidIndex(CurveIndex) ? CurveNames[CurveIndex].ToString() : FString());
            SetFiniteNumber(Row, TEXT("value"), FullCurves[CurveIndex]);
            if (!Writers.PoseCurveValues.Write(Row)) return false;
            ++Counts.PoseCurveValues;
        }
    }
    return true;
}

static bool ScanSkeletonSlots(USkeleton* Skeleton, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    if (!Skeleton) return true;
    const FString Path = Asset.GetSoftObjectPath().ToString();
    const FArrayProperty* GroupsProperty = CastField<FArrayProperty>(Skeleton->GetClass()->FindPropertyByName(TEXT("SlotGroups")));
    const FStructProperty* GroupStruct = GroupsProperty ? CastField<FStructProperty>(GroupsProperty->Inner) : nullptr;
    if (!GroupsProperty || !GroupStruct) return true;
    const void* Ptr = GroupsProperty->ContainerPtrToValuePtr<void>(Skeleton);
    FScriptArrayHelper Helper(GroupsProperty, Ptr);
    for (int32 GroupIndex = 0; GroupIndex < Helper.Num(); ++GroupIndex)
    {
        const void* Group = Helper.GetRawPtr(GroupIndex);
        const FString GroupName = GetNameField(GroupStruct->Struct, Group, TEXT("GroupName"));
        const TArray<FName> Slots = ReadNameArray(GroupStruct->Struct, Group, TEXT("SlotNames"));
        TSharedRef<FJsonObject> G = MakeShared<FJsonObject>();
        G->SetStringField(TEXT("skeleton_path"), Path); G->SetNumberField(TEXT("group_index"), GroupIndex);
        G->SetStringField(TEXT("group_name"), GroupName); G->SetNumberField(TEXT("slot_count"), Slots.Num());
        if (!Writers.SkeletonSlotGroups.Write(G)) return false; ++Counts.SkeletonSlotGroups;
        for (int32 SlotIndex = 0; SlotIndex < Slots.Num(); ++SlotIndex)
        {
            TSharedRef<FJsonObject> R = MakeShared<FJsonObject>();
            R->SetStringField(TEXT("skeleton_path"), Path); R->SetNumberField(TEXT("group_index"), GroupIndex); R->SetStringField(TEXT("group_name"), GroupName);
            R->SetNumberField(TEXT("slot_index"), SlotIndex); R->SetStringField(TEXT("slot_name"), Slots[SlotIndex].ToString());
            if (!Writers.SkeletonSlots.Write(R)) return false; ++Counts.SkeletonSlots;
        }
    }
    return true;
}

static bool ScanChooser(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    const int32 ResultCount = GetArrayCount(Object, TEXT("ResultsStructs"));
    const int32 ColumnCount = GetArrayCount(Object, TEXT("ColumnsStructs"));
    const int32 ContextCount = GetArrayCount(Object, TEXT("ContextData"));
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("chooser_path"), Path); Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("output_object_type"), GetObjectField(Object, TEXT("OutputObjectType")) ? GetObjectField(Object, TEXT("OutputObjectType"))->GetPathName() : FString());
    Summary->SetNumberField(TEXT("result_count"), ResultCount); Summary->SetNumberField(TEXT("column_count"), ColumnCount); Summary->SetNumberField(TEXT("context_count"), ContextCount);
    if (!Writers.ChooserTables.Write(Summary)) return false; ++Counts.ChooserTables;
    const TArray<bool> Disabled = ReadBoolArray(Object, TEXT("DisabledRows"));
    if (!WriteInstancedStructArray(Object, Path, TEXT("ColumnsStructs"), TEXT("chooser_column"), Writers.ChooserColumns, Counts.ChooserColumns, Writers, Counts)) return false;
    if (!WriteInstancedStructArray(Object, Path, TEXT("ResultsStructs"), TEXT("chooser_result"), Writers.ChooserResults, Counts.ChooserResults, Writers, Counts, &Disabled)) return false;
    if (!WriteInstancedStructArray(Object, Path, TEXT("ContextData"), TEXT("chooser_context"), Writers.ChooserContext, Counts.ChooserContext, Writers, Counts)) return false;
    return true;
}

static bool ScanProxyTable(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("proxy_table_path"), Path); Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetNumberField(TEXT("entry_count"), GetArrayCount(Object, TEXT("Entries"))); Summary->SetNumberField(TEXT("inheritance_count"), GetArrayCount(Object, TEXT("InheritEntries")));
    if (!Writers.ProxyTables.Write(Summary)) return false; ++Counts.ProxyTables;
    if (!WriteInstancedStructArray(Object, Path, TEXT("Entries"), TEXT("proxy_entry"), Writers.ProxyEntries, Counts.ProxyEntries, Writers, Counts)) return false;
    if (!WriteInstancedStructArray(Object, Path, TEXT("InheritEntries"), TEXT("proxy_inheritance"), Writers.ProxyInheritance, Counts.ProxyInheritance, Writers, Counts)) return false;
    return true;
}

static bool ScanIKRig(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    UObject* Skeleton = GetObjectField(Object, TEXT("Skeleton"));
    if (!Skeleton) Skeleton = GetObjectField(Object, TEXT("SkeletonAsset"));
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("ik_rig_path"), Path); Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("skeleton_path"), Skeleton ? Skeleton->GetPathName() : FString());
    Summary->SetStringField(TEXT("preview_mesh"), ExportObjectField(Object, TEXT("PreviewSkeletalMesh")));
    Summary->SetNumberField(TEXT("chain_count"), GetArrayCount(Object, TEXT("RetargetDefinition")));
    Summary->SetNumberField(TEXT("goal_count"), GetArrayCount(Object, TEXT("Goals")));
    Summary->SetNumberField(TEXT("solver_count"), GetArrayCount(Object, TEXT("SolverStack")));
    if (!Writers.IKRigs.Write(Summary)) return false; ++Counts.IKRigs;

    const FStructProperty* SkeletonProperty = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(TEXT("Skeleton")));
    if (SkeletonProperty)
    {
        const void* Skel = SkeletonProperty->ContainerPtrToValuePtr<void>(Object);
        const TArray<FName> Bones = ReadNameArray(SkeletonProperty->Struct, Skel, TEXT("BoneNames"));
        const TArray<int32> Parents = ReadIntArray(SkeletonProperty->Struct, Skel, TEXT("ParentIndices"));
        const TArray<FTransform> Poses = ReadTransformArray(SkeletonProperty->Struct, Skel, TEXT("CurrentPoseGlobal"));
        for (int32 Index = 0; Index < Bones.Num(); ++Index)
        {
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("ik_rig_path"), Path); Row->SetNumberField(TEXT("bone_index"), Index); Row->SetStringField(TEXT("bone_name"), Bones[Index].ToString());
            Row->SetNumberField(TEXT("parent_index"), Parents.IsValidIndex(Index) ? Parents[Index] : -1); if (Poses.IsValidIndex(Index)) SetTransform(Row, Poses[Index]);
            if (!Writers.IKRigBones.Write(Row)) return false; ++Counts.IKRigBones;
        }
    }

    FArrayProperty* ChainArray = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("RetargetDefinition")));
    if (ChainArray)
    {
        const FStructProperty* Container = CastField<FStructProperty>(ChainArray->Inner);
        const void* Ptr = ChainArray->ContainerPtrToValuePtr<void>(Object);
        FScriptArrayHelper H(ChainArray, Ptr);
        for (int32 I = 0; I < H.Num(); ++I)
        {
            const void* V = H.GetRawPtr(I); UStruct* S = Container ? Container->Struct : nullptr;
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>(); Row->SetStringField(TEXT("ik_rig_path"), Path); Row->SetNumberField(TEXT("chain_index"), I);
            Row->SetStringField(TEXT("chain_name"), GetNameField(S, V, TEXT("ChainName"))); Row->SetStringField(TEXT("start_bone"), GetNestedBoneName(S, V, TEXT("StartBone")));
            Row->SetStringField(TEXT("end_bone"), GetNestedBoneName(S, V, TEXT("EndBone"))); Row->SetStringField(TEXT("ik_goal_name"), GetNameField(S, V, TEXT("IKGoalName")));
            bool T=false; Row->SetStringField(TEXT("raw_value"), ExportProperty(ChainArray->Inner,V,Object,T));
            if (!Writers.IKRigChains.Write(Row)) return false; ++Counts.IKRigChains;
        }
    }
    if (!WriteInstancedStructArray(Object, Path, TEXT("Goals"), TEXT("ik_goal"), Writers.IKRigGoals, Counts.IKRigGoals, Writers, Counts)) return false;
    if (!WriteInstancedStructArray(Object, Path, TEXT("SolverStack"), TEXT("ik_solver"), Writers.IKRigSolvers, Counts.IKRigSolvers, Writers, Counts)) return false;
    return true;
}

static bool ScanIKRetargeter(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    UObject* Source = GetObjectField(Object, TEXT("SourceIKRigAsset")); if (!Source) Source = GetObjectField(Object, TEXT("SourceIKRig"));
    UObject* Target = GetObjectField(Object, TEXT("TargetIKRigAsset")); if (!Target) Target = GetObjectField(Object, TEXT("TargetIKRig"));
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>(); Summary->SetStringField(TEXT("ik_retargeter_path"), Path); Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("source_ik_rig"), Source ? Source->GetPathName() : FString()); Summary->SetStringField(TEXT("target_ik_rig"), Target ? Target->GetPathName() : FString());
    Summary->SetNumberField(TEXT("op_count"), GetArrayCount(Object, TEXT("RetargetOps")) + GetArrayCount(Object, TEXT("OpStack")));
    if (!Writers.IKRetargeters.Write(Summary)) return false; ++Counts.IKRetargeters;
    if (!WriteInstancedStructArray(Object, Path, TEXT("RetargetOps"), TEXT("ik_retarget_op"), Writers.IKRetargetOps, Counts.IKRetargetOps, Writers, Counts)) return false;
    if (!WriteInstancedStructArray(Object, Path, TEXT("OpStack"), TEXT("ik_retarget_op"), Writers.IKRetargetOps, Counts.IKRetargetOps, Writers, Counts)) return false;
    if (!WriteInstancedStructArray(Object, Path, TEXT("SourceRetargetPoses"), TEXT("ik_source_pose"), Writers.IKRetargetPoses, Counts.IKRetargetPoses, Writers, Counts)) return false;
    if (!WriteInstancedStructArray(Object, Path, TEXT("TargetRetargetPoses"), TEXT("ik_target_pose"), Writers.IKRetargetPoses, Counts.IKRetargetPoses, Writers, Counts)) return false;
    return true;
}

static bool SaveManifest(const FString& OutputDir, const FCounts& C, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), BreadthSchemaVersion); Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolAnimationBreadth"));
    Root->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601()); Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetBoolField(TEXT("success"), bSuccess); Root->SetStringField(TEXT("error"), Error);
    TSharedRef<FJsonObject> Counts = MakeShared<FJsonObject>();
    Counts->SetNumberField(TEXT("pose_assets"),C.PoseAssets); Counts->SetNumberField(TEXT("pose_asset_tracks"),C.PoseTracks); Counts->SetNumberField(TEXT("pose_asset_poses"),C.Poses);
    Counts->SetNumberField(TEXT("pose_asset_transforms"),C.PoseTransforms); Counts->SetNumberField(TEXT("pose_asset_curve_values"),C.PoseCurveValues); Counts->SetNumberField(TEXT("skeleton_slot_groups"),C.SkeletonSlotGroups); Counts->SetNumberField(TEXT("skeleton_slots"),C.SkeletonSlots);
    Counts->SetNumberField(TEXT("chooser_tables"),C.ChooserTables); Counts->SetNumberField(TEXT("chooser_columns"),C.ChooserColumns); Counts->SetNumberField(TEXT("chooser_results"),C.ChooserResults); Counts->SetNumberField(TEXT("chooser_context"),C.ChooserContext);
    Counts->SetNumberField(TEXT("proxy_tables"),C.ProxyTables); Counts->SetNumberField(TEXT("proxy_entries"),C.ProxyEntries); Counts->SetNumberField(TEXT("proxy_table_inheritance"),C.ProxyInheritance);
    Counts->SetNumberField(TEXT("ik_rigs"),C.IKRigs); Counts->SetNumberField(TEXT("ik_rig_bones"),C.IKRigBones); Counts->SetNumberField(TEXT("ik_rig_chains"),C.IKRigChains); Counts->SetNumberField(TEXT("ik_rig_goals"),C.IKRigGoals); Counts->SetNumberField(TEXT("ik_rig_solvers"),C.IKRigSolvers);
    Counts->SetNumberField(TEXT("ik_retargeters"),C.IKRetargeters); Counts->SetNumberField(TEXT("ik_retarget_ops"),C.IKRetargetOps); Counts->SetNumberField(TEXT("ik_retarget_poses"),C.IKRetargetPoses); Counts->SetNumberField(TEXT("animation_struct_references"),C.StructReferences);
    Root->SetObjectField(TEXT("counts"),Counts);
    static const TCHAR* Files[] = {TEXT("pose_assets.jsonl"),TEXT("pose_asset_tracks.jsonl"),TEXT("pose_asset_poses.jsonl"),TEXT("pose_asset_transforms.jsonl"),TEXT("pose_asset_curve_values.jsonl"),TEXT("skeleton_slot_groups.jsonl"),TEXT("skeleton_slots.jsonl"),TEXT("chooser_tables.jsonl"),TEXT("chooser_columns.jsonl"),TEXT("chooser_results.jsonl"),TEXT("chooser_context.jsonl"),TEXT("proxy_tables.jsonl"),TEXT("proxy_entries.jsonl"),TEXT("proxy_table_inheritance.jsonl"),TEXT("ik_rigs.jsonl"),TEXT("ik_rig_bones.jsonl"),TEXT("ik_rig_chains.jsonl"),TEXT("ik_rig_goals.jsonl"),TEXT("ik_rig_solvers.jsonl"),TEXT("ik_retargeters.jsonl"),TEXT("ik_retarget_ops.jsonl"),TEXT("ik_retarget_poses.jsonl"),TEXT("animation_struct_references.jsonl")};
    TArray<TSharedPtr<FJsonValue>> A; for (const TCHAR* F:Files) A.Add(MakeShared<FJsonValueString>(F)); Root->SetArrayField(TEXT("files"),A);
    FString Text; const auto W=TJsonWriterFactory<TCHAR,TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text); if(!FJsonSerializer::Serialize(Root,W)) return false;
    return FFileHelper::SaveStringToFile(Text,*FPaths::Combine(OutputDir,TEXT("animation_breadth_manifest.json")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunBreadthScan(FString& OutError)
{
    FString OutputDir; FParse::Value(FCommandLine::Get(),TEXT("Output="),OutputDir); const FString ProjectDir=NormalizeAbsolutePath(FPaths::ProjectDir());
    if(OutputDir.IsEmpty()) OutputDir=FPaths::Combine(ProjectDir,TEXT(".uatool")); else if(FPaths::IsRelative(OutputDir)) OutputDir=FPaths::Combine(ProjectDir,OutputDir); OutputDir=NormalizeAbsolutePath(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir,true); const bool bIncludeEngine=FParse::Param(FCommandLine::Get(),TEXT("IncludeEngine")); const bool bIncludeSelf=FParse::Param(FCommandLine::Get(),TEXT("IncludeSelf"));
    FString ToolPluginDir; if(const TSharedPtr<IPlugin> P=IPluginManager::Get().FindPlugin(TEXT("UnrealAssetTool"));P.IsValid()) ToolPluginDir=NormalizeAbsolutePath(P->GetBaseDir());
    FWriters W; FCounts C; if(!W.Open(OutputDir)){OutError=TEXT("could not create breadth animation outputs"); SaveManifest(OutputDir,C,false,OutError); return false;}
    FAssetRegistryModule& M=FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")); IAssetRegistry& R=M.Get(); R.SearchAllAssets(true); TArray<FAssetData>A;R.GetAllAssets(A,true);A.Sort([](const FAssetData&X,const FAssetData&Y){return X.GetSoftObjectPath().ToString()<Y.GetSoftObjectPath().ToString();});
    for(const FAssetData& Asset:A)
    {
        const FString CP=Asset.AssetClassPath.ToString(); const bool P=CP==TEXT("/Script/Engine.PoseAsset"), S=CP==TEXT("/Script/Engine.Skeleton"), Ch=CP==TEXT("/Script/Chooser.ChooserTable"), Pr=CP==TEXT("/Script/ProxyTable.ProxyTable"), IR=CP==TEXT("/Script/IKRig.IKRigDefinition"), Ret=CP==TEXT("/Script/IKRig.IKRetargeter"); if(!P&&!S&&!Ch&&!Pr&&!IR&&!Ret) continue;
        FString PF; const bool Disk=FPackageName::DoesPackageExist(Asset.PackageName.ToString(),&PF,false); if(!bIncludeSelf&&Disk&&!ToolPluginDir.IsEmpty()&&IsInsideDirectory(PF,ToolPluginDir))continue; if(!bIncludeEngine&&(!Disk||!IsInsideDirectory(PF,ProjectDir)))continue;
        UObject* O=Asset.GetAsset(); if(!O)continue; bool OK=true; if(P)OK=ScanPoseAsset(Cast<UPoseAsset>(O),Asset,W,C); else if(S)OK=ScanSkeletonSlots(Cast<USkeleton>(O),Asset,W,C); else if(Ch)OK=ScanChooser(O,Asset,W,C); else if(Pr)OK=ScanProxyTable(O,Asset,W,C); else if(IR)OK=ScanIKRig(O,Asset,W,C); else if(Ret)OK=ScanIKRetargeter(O,Asset,W,C); if(!OK){OutError=TEXT("failed breadth scan for ")+Asset.GetSoftObjectPath().ToString();SaveManifest(OutputDir,C,false,OutError);return false;}
    }
    if(!SaveManifest(OutputDir,C,true,FString())){OutError=TEXT("could not write animation_breadth_manifest.json");return false;} UE_LOG(LogTemp,Display,TEXT("UnrealAssetToolAnimationBreadth: pose_assets=%lld chooser=%lld proxy=%lld ik_rigs=%lld retargeters=%lld refs=%lld"),C.PoseAssets,C.ChooserTables,C.ProxyTables,C.IKRigs,C.IKRetargeters,C.StructReferences); return true;
}

static void OnPostEngineInit(){FString Run;FParse::Value(FCommandLine::Get(),TEXT("run="),Run);if(!Run.Equals(TEXT("UnrealAssetToolWorld"),ESearchCase::IgnoreCase))return;FString Error;if(!RunBreadthScan(Error))UE_LOG(LogTemp,Error,TEXT("UnrealAssetToolAnimationBreadth: %s"),*Error);}
struct FBootstrap{FBootstrap(){FCoreDelegates::GetOnPostEngineInit().AddStatic(&OnPostEngineInit);}}; static FBootstrap GBootstrap;
}
