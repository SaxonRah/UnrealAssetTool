#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Animation/PoseAsset.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Math/UnrealMathUtility.h"
#include "Misc/CommandLine.h"
#include "Misc/CoreDelegates.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolAnimationBreadthFinalize
{
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
    int64 PoseCurveValues = 0;
    int64 ChooserTables = 0;
    int64 ProxyTables = 0;
    int64 ProxyEntries = 0;
    int64 ProxyInheritance = 0;
    int64 IKRigs = 0;
    int64 IKRigBones = 0;
    int64 IKRigChains = 0;
    int64 IKRigGoals = 0;
    int64 IKRetargeters = 0;
    int64 IKRetargetPoses = 0;
};

struct FWriters
{
    FJsonlWriter PoseCurveValues;
    FJsonlWriter ChooserTables;
    FJsonlWriter ProxyTables;
    FJsonlWriter ProxyEntries;
    FJsonlWriter ProxyInheritance;
    FJsonlWriter IKRigs;
    FJsonlWriter IKRigBones;
    FJsonlWriter IKRigChains;
    FJsonlWriter IKRigGoals;
    FJsonlWriter IKRetargeters;
    FJsonlWriter IKRetargetPoses;

    bool Open(const FString& OutputDir)
    {
        return PoseCurveValues.Open(FPaths::Combine(OutputDir, TEXT("pose_asset_curve_values.jsonl"))) &&
            ChooserTables.Open(FPaths::Combine(OutputDir, TEXT("chooser_tables.jsonl"))) &&
            ProxyTables.Open(FPaths::Combine(OutputDir, TEXT("proxy_tables.jsonl"))) &&
            ProxyEntries.Open(FPaths::Combine(OutputDir, TEXT("proxy_entries.jsonl"))) &&
            ProxyInheritance.Open(FPaths::Combine(OutputDir, TEXT("proxy_table_inheritance.jsonl"))) &&
            IKRigs.Open(FPaths::Combine(OutputDir, TEXT("ik_rigs.jsonl"))) &&
            IKRigBones.Open(FPaths::Combine(OutputDir, TEXT("ik_rig_bones.jsonl"))) &&
            IKRigChains.Open(FPaths::Combine(OutputDir, TEXT("ik_rig_chains.jsonl"))) &&
            IKRigGoals.Open(FPaths::Combine(OutputDir, TEXT("ik_rig_goals.jsonl"))) &&
            IKRetargeters.Open(FPaths::Combine(OutputDir, TEXT("ik_retargeters.jsonl"))) &&
            IKRetargetPoses.Open(FPaths::Combine(OutputDir, TEXT("ik_retarget_poses.jsonl")));
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
    FString F = NormalizeAbsolutePath(File);
    FString D = NormalizeAbsolutePath(Directory);
    if (!D.EndsWith(TEXT("/")))
    {
        D.AppendChar(TEXT('/'));
    }
    return F.StartsWith(D, ESearchCase::IgnoreCase);
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

static FString ExportObjectField(UObject* Object, const FName FieldName)
{
    if (!Object)
    {
        return FString();
    }
    const FProperty* Property = Object->GetClass()->FindPropertyByName(FieldName);
    if (!Property)
    {
        return FString();
    }
    bool bTruncated = false;
    return ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(Object), Object, bTruncated);
}

static UObject* GetObjectField(UStruct* Struct, const void* StructValue, const FName FieldName)
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

static UObject* GetObjectField(UObject* Object, const FName FieldName)
{
    return Object ? GetObjectField(Object->GetClass(), Object, FieldName) : nullptr;
}

static FString GetNameField(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    if (!Struct || !StructValue)
    {
        return FString();
    }
    if (const FNameProperty* Property = CastField<FNameProperty>(Struct->FindPropertyByName(FieldName)))
    {
        const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructValue);
        return ValuePtr ? Property->GetPropertyValue(ValuePtr).ToString() : FString();
    }
    const FProperty* Property = Struct->FindPropertyByName(FieldName);
    if (!Property)
    {
        return FString();
    }
    bool bTruncated = false;
    FString Value = ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(StructValue), nullptr, bTruncated);
    Value.TrimStartAndEndInline();
    if (Value.StartsWith(TEXT("\"") ) && Value.EndsWith(TEXT("\"")) && Value.Len() >= 2)
    {
        Value = Value.Mid(1, Value.Len() - 2);
    }
    return Value;
}

static FString GetNestedBoneName(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    if (!Struct || !StructValue)
    {
        return FString();
    }
    const FStructProperty* Property = CastField<FStructProperty>(Struct->FindPropertyByName(FieldName));
    if (!Property)
    {
        return FString();
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructValue);
    return GetNameField(Property->Struct, ValuePtr, TEXT("BoneName"));
}

static TArray<FName> ReadNameArray(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    TArray<FName> Out;
    if (!Struct || !StructValue)
    {
        return Out;
    }
    FArrayProperty* Array = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
    const FNameProperty* Inner = Array ? CastField<FNameProperty>(Array->Inner) : nullptr;
    if (!Array || !Inner)
    {
        return Out;
    }
    const void* ValuePtr = Array->ContainerPtrToValuePtr<void>(StructValue);
    if (!ValuePtr)
    {
        return Out;
    }
    FScriptArrayHelper Helper(Array, ValuePtr);
    Out.Reserve(Helper.Num());
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        Out.Add(Inner->GetPropertyValue(Helper.GetRawPtr(Index)));
    }
    return Out;
}

static TArray<int32> ReadIntArray(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    TArray<int32> Out;
    if (!Struct || !StructValue)
    {
        return Out;
    }
    FArrayProperty* Array = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
    const FNumericProperty* Inner = Array ? CastField<FNumericProperty>(Array->Inner) : nullptr;
    if (!Array || !Inner || !Inner->IsInteger())
    {
        return Out;
    }
    const void* ValuePtr = Array->ContainerPtrToValuePtr<void>(StructValue);
    if (!ValuePtr)
    {
        return Out;
    }
    FScriptArrayHelper Helper(Array, ValuePtr);
    Out.Reserve(Helper.Num());
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        Out.Add(static_cast<int32>(Inner->GetSignedIntPropertyValue(Helper.GetRawPtr(Index))));
    }
    return Out;
}

static TArray<FTransform> ReadTransformArray(UStruct* Struct, const void* StructValue, const FName FieldName)
{
    TArray<FTransform> Out;
    if (!Struct || !StructValue)
    {
        return Out;
    }
    FArrayProperty* Array = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
    const FStructProperty* Inner = Array ? CastField<FStructProperty>(Array->Inner) : nullptr;
    if (!Array || !Inner || Inner->Struct != TBaseStructure<FTransform>::Get())
    {
        return Out;
    }
    const void* ValuePtr = Array->ContainerPtrToValuePtr<void>(StructValue);
    if (!ValuePtr)
    {
        return Out;
    }
    FScriptArrayHelper Helper(Array, ValuePtr);
    Out.Reserve(Helper.Num());
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        Out.Add(*reinterpret_cast<const FTransform*>(Helper.GetRawPtr(Index)));
    }
    return Out;
}

static FString StructTypeFromExport(const FString& Value)
{
    FString Trimmed = Value.TrimStartAndEnd();
    const int32 Open = Trimmed.Find(TEXT("("));
    return Open > 0 && Trimmed.StartsWith(TEXT("/Script/")) ? Trimmed.Left(Open) : FString();
}

static void SetNullableNumber(const TSharedRef<FJsonObject>& Row, const TCHAR* FieldName, const float Value, const bool bValid)
{
    if (bValid && FMath::IsFinite(Value))
    {
        Row->SetNumberField(FieldName, Value);
    }
    else
    {
        Row->SetField(FieldName, MakeShared<FJsonValueNull>());
    }
}

static void SetTransform(const TSharedRef<FJsonObject>& Row, const FTransform& Transform)
{
    const FVector T = Transform.GetTranslation();
    const FQuat R = Transform.GetRotation();
    const FVector S = Transform.GetScale3D();
    Row->SetNumberField(TEXT("translation_x"), T.X);
    Row->SetNumberField(TEXT("translation_y"), T.Y);
    Row->SetNumberField(TEXT("translation_z"), T.Z);
    Row->SetNumberField(TEXT("rotation_x"), R.X);
    Row->SetNumberField(TEXT("rotation_y"), R.Y);
    Row->SetNumberField(TEXT("rotation_z"), R.Z);
    Row->SetNumberField(TEXT("rotation_w"), R.W);
    Row->SetNumberField(TEXT("scale_x"), S.X);
    Row->SetNumberField(TEXT("scale_y"), S.Y);
    Row->SetNumberField(TEXT("scale_z"), S.Z);
}

static bool ScanPoseCurveValues(UPoseAsset* Pose, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    if (!Pose)
    {
        return true;
    }
    const FString Path = Asset.GetSoftObjectPath().ToString();
    const TArray<FName>& PoseNames = Pose->GetPoseFNames();
    const TArray<FName> CurveNames = Pose->GetCurveFNames();
    for (int32 PoseIndex = 0; PoseIndex < Pose->GetNumPoses(); ++PoseIndex)
    {
        const TArray<float>& RawCurves = Pose->GetRawCurveValues(PoseIndex);
        const TArray<float>& FullCurves = Pose->GetFullCurveValues(PoseIndex);
        for (int32 CurveIndex = 0; CurveIndex < FullCurves.Num(); ++CurveIndex)
        {
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("pose_asset_path"), Path);
            Row->SetNumberField(TEXT("pose_index"), PoseIndex);
            Row->SetStringField(TEXT("pose_name"), PoseNames.IsValidIndex(PoseIndex) ? PoseNames[PoseIndex].ToString() : FString());
            Row->SetNumberField(TEXT("curve_index"), CurveIndex);
            Row->SetStringField(TEXT("curve_name"), CurveNames.IsValidIndex(CurveIndex) ? CurveNames[CurveIndex].ToString() : FString());
            SetNullableNumber(Row, TEXT("raw_value"), RawCurves.IsValidIndex(CurveIndex) ? RawCurves[CurveIndex] : 0.0f, RawCurves.IsValidIndex(CurveIndex));
            SetNullableNumber(Row, TEXT("full_value"), FullCurves[CurveIndex], true);
            if (!Writers.PoseCurveValues.Write(Row))
            {
                return false;
            }
            ++Counts.PoseCurveValues;
        }
    }
    return true;
}

static bool ScanChooserSummary(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    const auto CountArray = [Object](const FName Name) -> int32
    {
        FArrayProperty* Array = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(Name));
        if (!Array)
        {
            return 0;
        }
        const void* ValuePtr = Array->ContainerPtrToValuePtr<void>(Object);
        return ValuePtr ? FScriptArrayHelper(Array, ValuePtr).Num() : 0;
    };
    int32 DisabledCount = 0;
    if (FArrayProperty* Disabled = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("DisabledRows"))))
    {
        const FBoolProperty* Inner = CastField<FBoolProperty>(Disabled->Inner);
        const void* ValuePtr = Disabled->ContainerPtrToValuePtr<void>(Object);
        if (Inner && ValuePtr)
        {
            FScriptArrayHelper Helper(Disabled, ValuePtr);
            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                DisabledCount += Inner->GetPropertyValue(Helper.GetRawPtr(Index)) ? 1 : 0;
            }
        }
    }
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("chooser_path"), Path);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    if (UObject* OutputType = GetObjectField(Object, TEXT("OutputObjectType")))
    {
        Row->SetStringField(TEXT("output_object_type"), OutputType->GetPathName());
    }
    else
    {
        Row->SetStringField(TEXT("output_object_type"), FString());
    }
    Row->SetNumberField(TEXT("column_count"), CountArray(TEXT("ColumnsStructs")));
    Row->SetNumberField(TEXT("result_count"), CountArray(TEXT("ResultsStructs")));
    Row->SetNumberField(TEXT("context_count"), CountArray(TEXT("ContextData")));
    Row->SetNumberField(TEXT("disabled_row_count"), DisabledCount);
    if (!Writers.ChooserTables.Write(Row))
    {
        return false;
    }
    ++Counts.ChooserTables;
    return true;
}

static bool ScanProxyTable(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    int32 EntryCount = 0;
    int32 InheritCount = 0;

    if (FArrayProperty* Entries = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("Entries"))))
    {
        const FStructProperty* EntryStruct = CastField<FStructProperty>(Entries->Inner);
        const void* ValuePtr = Entries->ContainerPtrToValuePtr<void>(Object);
        if (EntryStruct && ValuePtr)
        {
            FScriptArrayHelper Helper(Entries, ValuePtr);
            EntryCount = Helper.Num();
            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                const void* Entry = Helper.GetRawPtr(Index);
                UObject* Proxy = GetObjectField(EntryStruct->Struct, Entry, TEXT("Proxy"));
                const FProperty* ValueStructProperty = EntryStruct->Struct->FindPropertyByName(TEXT("ValueStruct"));
                bool bTruncated = false;
                const FString ValueRaw = ValueStructProperty
                    ? ExportProperty(ValueStructProperty, ValueStructProperty->ContainerPtrToValuePtr<void>(Entry), Object, bTruncated)
                    : FString();
                bool bEntryTruncated = false;
                const FString RawEntry = ExportProperty(Entries->Inner, Entry, Object, bEntryTruncated);
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("proxy_table_path"), Path);
                Row->SetNumberField(TEXT("entry_index"), Index);
                Row->SetStringField(TEXT("proxy_path"), Proxy ? Proxy->GetPathName() : FString());
                Row->SetStringField(TEXT("value_struct_type"), StructTypeFromExport(ValueRaw));
                Row->SetStringField(TEXT("value_raw"), ValueRaw);
                Row->SetStringField(TEXT("raw_value"), RawEntry);
                Row->SetBoolField(TEXT("truncated"), bTruncated || bEntryTruncated);
                if (!Writers.ProxyEntries.Write(Row))
                {
                    return false;
                }
                ++Counts.ProxyEntries;
            }
        }
    }

    if (FArrayProperty* Inherit = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("InheritEntriesFrom"))))
    {
        const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Inherit->Inner);
        const void* ValuePtr = Inherit->ContainerPtrToValuePtr<void>(Object);
        if (Inner && ValuePtr)
        {
            FScriptArrayHelper Helper(Inherit, ValuePtr);
            InheritCount = Helper.Num();
            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                UObject* Parent = Inner->GetObjectPropertyValue(Helper.GetRawPtr(Index));
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("proxy_table_path"), Path);
                Row->SetNumberField(TEXT("inherit_index"), Index);
                Row->SetStringField(TEXT("parent_table_path"), Parent ? Parent->GetPathName() : FString());
                if (!Writers.ProxyInheritance.Write(Row))
                {
                    return false;
                }
                ++Counts.ProxyInheritance;
            }
        }
    }

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("proxy_table_path"), Path);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetNumberField(TEXT("entry_count"), EntryCount);
    Summary->SetNumberField(TEXT("inherit_table_count"), InheritCount);
    if (!Writers.ProxyTables.Write(Summary))
    {
        return false;
    }
    ++Counts.ProxyTables;
    return true;
}

static bool ScanIKRig(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    FString PreviewMeshPath = ExportObjectField(Object, TEXT("PreviewSkeletalMesh"));
    FString RootBone;
    FString PelvisBone;
    int32 ChainCount = 0;
    int32 BoneCount = 0;

    const FStructProperty* SkeletonProperty = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(TEXT("Skeleton")));
    if (SkeletonProperty)
    {
        const void* SkeletonValue = SkeletonProperty->ContainerPtrToValuePtr<void>(Object);
        const TArray<FName> Bones = ReadNameArray(SkeletonProperty->Struct, SkeletonValue, TEXT("BoneNames"));
        const TArray<int32> Parents = ReadIntArray(SkeletonProperty->Struct, SkeletonValue, TEXT("ParentIndices"));
        const TArray<FTransform> Poses = ReadTransformArray(SkeletonProperty->Struct, SkeletonValue, TEXT("CurrentPoseGlobal"));
        const TArray<FName> Excluded = ReadNameArray(SkeletonProperty->Struct, SkeletonValue, TEXT("ExcludedBones"));
        const TSet<FName> ExcludedSet(Excluded);
        BoneCount = Bones.Num();
        for (int32 Index = 0; Index < Bones.Num(); ++Index)
        {
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("ik_rig_path"), Path);
            Row->SetNumberField(TEXT("bone_index"), Index);
            Row->SetStringField(TEXT("bone_name"), Bones[Index].ToString());
            Row->SetNumberField(TEXT("parent_index"), Parents.IsValidIndex(Index) ? Parents[Index] : -1);
            Row->SetBoolField(TEXT("excluded"), ExcludedSet.Contains(Bones[Index]));
            if (Poses.IsValidIndex(Index))
            {
                SetTransform(Row, Poses[Index]);
            }
            if (!Writers.IKRigBones.Write(Row))
            {
                return false;
            }
            ++Counts.IKRigBones;
        }
    }

    const FStructProperty* DefinitionProperty = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(TEXT("RetargetDefinition")));
    if (DefinitionProperty)
    {
        const void* Definition = DefinitionProperty->ContainerPtrToValuePtr<void>(Object);
        RootBone = GetNameField(DefinitionProperty->Struct, Definition, TEXT("RootBone"));
        PelvisBone = GetNameField(DefinitionProperty->Struct, Definition, TEXT("PelvisBone"));
        FArrayProperty* Chains = CastField<FArrayProperty>(DefinitionProperty->Struct->FindPropertyByName(TEXT("BoneChains")));
        const FStructProperty* ChainStruct = Chains ? CastField<FStructProperty>(Chains->Inner) : nullptr;
        const void* ChainsValue = Chains ? Chains->ContainerPtrToValuePtr<void>(Definition) : nullptr;
        if (Chains && ChainStruct && ChainsValue)
        {
            FScriptArrayHelper Helper(Chains, ChainsValue);
            ChainCount = Helper.Num();
            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                const void* Chain = Helper.GetRawPtr(Index);
                bool bTruncated = false;
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("ik_rig_path"), Path);
                Row->SetNumberField(TEXT("chain_index"), Index);
                Row->SetStringField(TEXT("chain_name"), GetNameField(ChainStruct->Struct, Chain, TEXT("ChainName")));
                Row->SetStringField(TEXT("start_bone"), GetNestedBoneName(ChainStruct->Struct, Chain, TEXT("StartBone")));
                Row->SetStringField(TEXT("end_bone"), GetNestedBoneName(ChainStruct->Struct, Chain, TEXT("EndBone")));
                Row->SetStringField(TEXT("ik_goal_name"), GetNameField(ChainStruct->Struct, Chain, TEXT("IKGoalName")));
                Row->SetStringField(TEXT("raw_value"), ExportProperty(Chains->Inner, Chain, Object, bTruncated));
                Row->SetBoolField(TEXT("truncated"), bTruncated);
                if (!Writers.IKRigChains.Write(Row))
                {
                    return false;
                }
                ++Counts.IKRigChains;
            }
        }
    }

    int32 GoalCount = 0;
    if (FArrayProperty* Goals = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("Goals"))))
    {
        const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Goals->Inner);
        const void* GoalsValue = Goals->ContainerPtrToValuePtr<void>(Object);
        if (Inner && GoalsValue)
        {
            FScriptArrayHelper Helper(Goals, GoalsValue);
            GoalCount = Helper.Num();
            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                UObject* Goal = Inner->GetObjectPropertyValue(Helper.GetRawPtr(Index));
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("ik_rig_path"), Path);
                Row->SetNumberField(TEXT("goal_index"), Index);
                Row->SetStringField(TEXT("goal_name"), Goal ? GetNameField(Goal->GetClass(), Goal, TEXT("GoalName")) : FString());
                Row->SetStringField(TEXT("bone_name"), Goal ? GetNameField(Goal->GetClass(), Goal, TEXT("BoneName")) : FString());
                Row->SetStringField(TEXT("goal_path"), Goal ? Goal->GetPathName() : FString());
                if (!Writers.IKRigGoals.Write(Row))
                {
                    return false;
                }
                ++Counts.IKRigGoals;
            }
        }
    }

    int32 SolverCount = 0;
    if (FArrayProperty* Solvers = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("SolverStack"))))
    {
        const void* SolverValue = Solvers->ContainerPtrToValuePtr<void>(Object);
        SolverCount = SolverValue ? FScriptArrayHelper(Solvers, SolverValue).Num() : 0;
    }

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("ik_rig_path"), Path);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("preview_mesh_path"), PreviewMeshPath);
    Summary->SetStringField(TEXT("skeleton_mesh_path"), PreviewMeshPath);
    Summary->SetStringField(TEXT("root_bone"), RootBone);
    Summary->SetStringField(TEXT("pelvis_bone"), PelvisBone);
    Summary->SetNumberField(TEXT("bone_count"), BoneCount);
    Summary->SetNumberField(TEXT("chain_count"), ChainCount);
    Summary->SetNumberField(TEXT("goal_count"), GoalCount);
    Summary->SetNumberField(TEXT("solver_count"), SolverCount);
    if (!Writers.IKRigs.Write(Summary))
    {
        return false;
    }
    ++Counts.IKRigs;
    return true;
}

static FString GetMapKeyName(const FProperty* KeyProperty, const void* KeyPtr, UObject* Owner)
{
    if (const FNameProperty* NameProperty = CastField<FNameProperty>(KeyProperty))
    {
        return NameProperty->GetPropertyValue(KeyPtr).ToString();
    }
    if (const FStrProperty* StringProperty = CastField<FStrProperty>(KeyProperty))
    {
        return StringProperty->GetPropertyValue(KeyPtr);
    }
    bool bTruncated = false;
    FString Value = ExportProperty(KeyProperty, KeyPtr, Owner, bTruncated);
    Value.TrimStartAndEndInline();
    if (Value.StartsWith(TEXT("\"") ) && Value.EndsWith(TEXT("\"")) && Value.Len() >= 2)
    {
        Value = Value.Mid(1, Value.Len() - 2);
    }
    return Value;
}

static bool ScanRetargetPoseMap(UObject* Object, const FString& Path, const FName PropertyName, const FString& Side, FWriters& Writers, FCounts& Counts, int32& OutCount)
{
    OutCount = 0;
    FMapProperty* Map = CastField<FMapProperty>(Object->GetClass()->FindPropertyByName(PropertyName));
    if (!Map)
    {
        return true;
    }
    const void* MapValue = Map->ContainerPtrToValuePtr<void>(Object);
    if (!MapValue)
    {
        return true;
    }
    FScriptMapHelper Helper(Map, MapValue);
    int32 PoseIndex = 0;
    for (int32 InternalIndex = 0; InternalIndex < Helper.GetMaxIndex(); ++InternalIndex)
    {
        if (!Helper.IsValidIndex(InternalIndex))
        {
            continue;
        }
        const void* KeyPtr = Helper.GetKeyPtr(InternalIndex);
        const void* ValuePtr = Helper.GetValuePtr(InternalIndex);
        bool bTruncated = false;
        const FString Raw = ExportProperty(Map->ValueProp, ValuePtr, Object, bTruncated);
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("retargeter_path"), Path);
        Row->SetStringField(TEXT("side"), Side);
        Row->SetNumberField(TEXT("pose_index"), PoseIndex++);
        Row->SetStringField(TEXT("pose_name"), GetMapKeyName(Map->KeyProp, KeyPtr, Object));
        Row->SetStringField(TEXT("raw_value"), Raw);
        Row->SetBoolField(TEXT("truncated"), bTruncated);
        if (!Writers.IKRetargetPoses.Write(Row))
        {
            return false;
        }
        ++Counts.IKRetargetPoses;
        ++OutCount;
    }
    return true;
}

static bool ScanIKRetargeter(UObject* Object, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Asset.GetSoftObjectPath().ToString();
    UObject* Source = GetObjectField(Object, TEXT("SourceIKRigAsset"));
    UObject* Target = GetObjectField(Object, TEXT("TargetIKRigAsset"));
    int32 OpCount = 0;
    if (FArrayProperty* Ops = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("RetargetOps"))))
    {
        const void* ValuePtr = Ops->ContainerPtrToValuePtr<void>(Object);
        OpCount = ValuePtr ? FScriptArrayHelper(Ops, ValuePtr).Num() : 0;
    }
    int32 SourcePoseCount = 0;
    int32 TargetPoseCount = 0;
    if (!ScanRetargetPoseMap(Object, Path, TEXT("SourceRetargetPoses"), TEXT("source"), Writers, Counts, SourcePoseCount))
    {
        return false;
    }
    if (!ScanRetargetPoseMap(Object, Path, TEXT("TargetRetargetPoses"), TEXT("target"), Writers, Counts, TargetPoseCount))
    {
        return false;
    }
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("retargeter_path"), Path);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("source_ik_rig_path"), Source ? Source->GetPathName() : FString());
    Summary->SetStringField(TEXT("target_ik_rig_path"), Target ? Target->GetPathName() : FString());
    Summary->SetNumberField(TEXT("op_count"), OpCount);
    Summary->SetNumberField(TEXT("source_pose_count"), SourcePoseCount);
    Summary->SetNumberField(TEXT("target_pose_count"), TargetPoseCount);
    if (!Writers.IKRetargeters.Write(Summary))
    {
        return false;
    }
    ++Counts.IKRetargeters;
    return true;
}

static bool LoadBreadthManifest(const FString& OutputDir, TSharedPtr<FJsonObject>& OutRoot)
{
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *FPaths::Combine(OutputDir, TEXT("animation_breadth_manifest.json"))))
    {
        return false;
    }
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
    return FJsonSerializer::Deserialize(Reader, OutRoot) && OutRoot.IsValid();
}

static bool SaveBreadthManifest(const FString& OutputDir, const TSharedPtr<FJsonObject>& Root)
{
    if (!Root.IsValid())
    {
        return false;
    }
    FString Text;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root.ToSharedRef(), Writer))
    {
        return false;
    }
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("animation_breadth_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool UpdateBreadthManifest(const FString& OutputDir, const FCounts& C, const bool bSuccess, const FString& Error)
{
    TSharedPtr<FJsonObject> Root;
    if (!LoadBreadthManifest(OutputDir, Root))
    {
        return false;
    }
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    TSharedPtr<FJsonObject> Counts = Root->GetObjectField(TEXT("counts"));
    if (!Counts.IsValid())
    {
        Counts = MakeShared<FJsonObject>();
        Root->SetObjectField(TEXT("counts"), Counts.ToSharedRef());
    }
    Counts->SetNumberField(TEXT("pose_asset_curve_values"), C.PoseCurveValues);
    Counts->SetNumberField(TEXT("chooser_tables"), C.ChooserTables);
    Counts->SetNumberField(TEXT("proxy_tables"), C.ProxyTables);
    Counts->SetNumberField(TEXT("proxy_entries"), C.ProxyEntries);
    Counts->SetNumberField(TEXT("proxy_table_inheritance"), C.ProxyInheritance);
    Counts->SetNumberField(TEXT("ik_rigs"), C.IKRigs);
    Counts->SetNumberField(TEXT("ik_rig_bones"), C.IKRigBones);
    Counts->SetNumberField(TEXT("ik_rig_chains"), C.IKRigChains);
    Counts->SetNumberField(TEXT("ik_rig_goals"), C.IKRigGoals);
    Counts->SetNumberField(TEXT("ik_retargeters"), C.IKRetargeters);
    Counts->SetNumberField(TEXT("ik_retarget_poses"), C.IKRetargetPoses);
    return SaveBreadthManifest(OutputDir, Root);
}

static bool RunFinalize(FString& OutError)
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

    TSharedPtr<FJsonObject> ExistingManifest;
    if (!LoadBreadthManifest(OutputDir, ExistingManifest) || !ExistingManifest->GetBoolField(TEXT("success")))
    {
        return true;
    }

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
        OutError = TEXT("could not create normalized breadth outputs");
        UpdateBreadthManifest(OutputDir, Counts, false, OutError);
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

    for (const FAssetData& Asset : Assets)
    {
        const FString ClassPath = Asset.AssetClassPath.ToString();
        const bool bPose = ClassPath == TEXT("/Script/Engine.PoseAsset");
        const bool bChooser = ClassPath == TEXT("/Script/Chooser.ChooserTable");
        const bool bProxy = ClassPath == TEXT("/Script/ProxyTable.ProxyTable");
        const bool bIKRig = ClassPath == TEXT("/Script/IKRig.IKRigDefinition");
        const bool bRetargeter = ClassPath == TEXT("/Script/IKRig.IKRetargeter");
        if (!bPose && !bChooser && !bProxy && !bIKRig && !bRetargeter)
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
        bool bOk = true;
        if (bPose)
        {
            bOk = ScanPoseCurveValues(Cast<UPoseAsset>(Object), Asset, Writers, Counts);
        }
        else if (bChooser)
        {
            bOk = ScanChooserSummary(Object, Asset, Writers, Counts);
        }
        else if (bProxy)
        {
            bOk = ScanProxyTable(Object, Asset, Writers, Counts);
        }
        else if (bIKRig)
        {
            bOk = ScanIKRig(Object, Asset, Writers, Counts);
        }
        else if (bRetargeter)
        {
            bOk = ScanIKRetargeter(Object, Asset, Writers, Counts);
        }
        if (!bOk)
        {
            OutError = TEXT("failed to normalize breadth asset ") + Asset.GetSoftObjectPath().ToString();
            UpdateBreadthManifest(OutputDir, Counts, false, OutError);
            return false;
        }
    }

    if (!UpdateBreadthManifest(OutputDir, Counts, true, FString()))
    {
        OutError = TEXT("could not update animation_breadth_manifest.json after normalization");
        return false;
    }

    UE_LOG(LogTemp, Display,
        TEXT("UnrealAssetToolAnimationBreadthFinalize: pose_curves=%lld chooser=%lld proxy_entries=%lld ik_chains=%lld ik_goals=%lld retarget_poses=%lld"),
        Counts.PoseCurveValues,
        Counts.ChooserTables,
        Counts.ProxyEntries,
        Counts.IKRigChains,
        Counts.IKRigGoals,
        Counts.IKRetargetPoses);
    return true;
}

static void OnCommandletPostMain()
{
    FString RunCommandlet;
    FParse::Value(FCommandLine::Get(), TEXT("run="), RunCommandlet);
    if (!RunCommandlet.Equals(TEXT("UnrealAssetToolWorld"), ESearchCase::IgnoreCase))
    {
        return;
    }
    FString Error;
    if (!RunFinalize(Error))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolAnimationBreadthFinalize: %s"), *Error);
    }
}

struct FBootstrap
{
    FBootstrap()
    {
        FCoreDelegates::OnCommandletPostMain.AddStatic(&OnCommandletPostMain);
    }
};

static FBootstrap GBootstrap;
}
