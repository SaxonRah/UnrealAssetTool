#include "UnrealAssetToolUAFCommandlet.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "RigVMModel/RigVMGraph.h"
#include "RigVMModel/RigVMLink.h"
#include "RigVMModel/RigVMNode.h"
#include "RigVMModel/RigVMPin.h"
#include "RigVMModel/Nodes/RigVMUnitNode.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UObjectHash.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolUAF
{
constexpr int32 SchemaVersion = 1;
constexpr int32 MaxExportChars = 65536;
constexpr int32 MaxDepth = 16;
constexpr int32 MaxContainerElements = 4096;
constexpr int32 MaxPropertyRowsPerOwner = 65536;

static const TCHAR* MountRoots[] = {
    TEXT("/UAF"),
    TEXT("/UAFAnimGraph"),
    TEXT("/UAFSharedAssets"),
};

struct FCounts
{
    int64 RegistryCandidates = 0;
    int64 LoadedAssets = 0;
    int64 AssetProperties = 0;
    int64 AssetReferences = 0;
    int64 Subobjects = 0;
    int64 SubobjectProperties = 0;
    int64 SubobjectReferences = 0;
    int64 RigVMGraphs = 0;
    int64 RigVMNodes = 0;
    int64 RigVMPins = 0;
    int64 RigVMLinks = 0;
    int64 UnitNodes = 0;
    int64 TruncatedProperties = 0;
    int64 PropertyDepthLimitHits = 0;
    int64 PropertyRowLimitHits = 0;
    int64 ContainerElementLimitHits = 0;
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

struct FWriters
{
    FJsonlWriter Assets;
    FJsonlWriter AssetProperties;
    FJsonlWriter AssetReferences;
    FJsonlWriter Subobjects;
    FJsonlWriter SubobjectProperties;
    FJsonlWriter SubobjectReferences;
    FJsonlWriter Graphs;
    FJsonlWriter Nodes;
    FJsonlWriter Pins;
    FJsonlWriter Links;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("uaf_assets.jsonl"))) &&
            AssetProperties.Open(FPaths::Combine(OutputDir, TEXT("uaf_asset_properties.jsonl"))) &&
            AssetReferences.Open(FPaths::Combine(OutputDir, TEXT("uaf_asset_references.jsonl"))) &&
            Subobjects.Open(FPaths::Combine(OutputDir, TEXT("uaf_subobjects.jsonl"))) &&
            SubobjectProperties.Open(FPaths::Combine(OutputDir, TEXT("uaf_subobject_properties.jsonl"))) &&
            SubobjectReferences.Open(FPaths::Combine(OutputDir, TEXT("uaf_subobject_references.jsonl"))) &&
            Graphs.Open(FPaths::Combine(OutputDir, TEXT("uaf_rigvm_graphs.jsonl"))) &&
            Nodes.Open(FPaths::Combine(OutputDir, TEXT("uaf_rigvm_nodes.jsonl"))) &&
            Pins.Open(FPaths::Combine(OutputDir, TEXT("uaf_rigvm_pins.jsonl"))) &&
            Links.Open(FPaths::Combine(OutputDir, TEXT("uaf_rigvm_links.jsonl")));
    }

    bool Close()
    {
        bool bOk = true;
        bOk = Assets.Close() && bOk;
        bOk = AssetProperties.Close() && bOk;
        bOk = AssetReferences.Close() && bOk;
        bOk = Subobjects.Close() && bOk;
        bOk = SubobjectProperties.Close() && bOk;
        bOk = SubobjectReferences.Close() && bOk;
        bOk = Graphs.Close() && bOk;
        bOk = Nodes.Close() && bOk;
        bOk = Pins.Close() && bOk;
        bOk = Links.Close() && bOk;
        return bOk;
    }
};

struct FOwnerState
{
    int32 Rows = 0;
};

static bool ShouldInspectProperty(const FProperty* Property)
{
    if (!Property) return false;
    constexpr EPropertyFlags Rejected =
        CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient |
        CPF_Deprecated | CPF_SkipSerialization;
    return !Property->HasAnyPropertyFlags(Rejected);
}

static FString ExportProperty(
    const FProperty* Property,
    const void* ValuePtr,
    UObject* ExportOwner,
    bool& bTruncated)
{
    bTruncated = false;
    if (!Property || !ValuePtr) return FString();
    FString Text;
    Property->ExportTextItem_Direct(Text, ValuePtr, nullptr, ExportOwner, PPF_None, nullptr);
    if (Text.Len() > MaxExportChars)
    {
        Text.LeftInline(MaxExportChars, EAllowShrinking::No);
        bTruncated = true;
    }
    return Text;
}

static bool WriteReference(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& AssetPath,
    const FString& OwnerPath,
    const FString& OwnerKind,
    const FString& OwnerType,
    const FString& RootProperty,
    const FString& PropertyPath,
    FJsonlWriter& Writer,
    int64& Count)
{
    FString TargetPath;
    FString TargetClass;
    FString Kind;

    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* Ptr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (Ptr && !Ptr->IsNull())
        {
            TargetPath = Ptr->ToSoftObjectPath().ToString();
            Kind = TEXT("soft_object");
        }
    }
    else if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        if (UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr))
        {
            TargetPath = Target->GetPathName();
            TargetClass = Target->GetClass()->GetPathName();
            Kind = TEXT("hard_object");
        }
    }

    if (TargetPath.IsEmpty()) return true;

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("owner_path"), OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), OwnerKind);
    Row->SetStringField(TEXT("owner_type"), OwnerType);
    Row->SetStringField(TEXT("root_property"), RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), Kind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (!Writer.Write(Row)) return false;
    ++Count;
    return true;
}

static int32 ContainerElementCount(const FProperty* Property, const void* ValuePtr)
{
    if (!Property || !ValuePtr) return -1;
    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, const_cast<void*>(ValuePtr));
        return Helper.Num();
    }
    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, const_cast<void*>(ValuePtr));
        return Helper.Num();
    }
    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, const_cast<void*>(ValuePtr));
        return Helper.Num();
    }
    return -1;
}

static bool WritePropertyRecursive(
    const FProperty* Property,
    const void* ValuePtr,
    const void* DefaultPtr,
    UObject* ExportOwner,
    UObject* DefaultExportOwner,
    const FString& AssetPath,
    const FString& OwnerPath,
    const FString& OwnerKind,
    const FString& OwnerType,
    const FString& RootProperty,
    const FString& PropertyPath,
    int32 Depth,
    FJsonlWriter& PropertyWriter,
    FJsonlWriter& ReferenceWriter,
    FOwnerState& State,
    FCounts& Counts,
    int64& PropertyCount,
    int64& ReferenceCount)
{
    if (!Property || !ValuePtr || !ShouldInspectProperty(Property)) return true;
    if (State.Rows >= MaxPropertyRowsPerOwner)
    {
        ++Counts.PropertyRowLimitHits;
        return true;
    }

    bool bTruncated = false;
    const FString Value = ExportProperty(Property, ValuePtr, ExportOwner, bTruncated);
    bool bDefaultTruncated = false;
    const FString DefaultValue = DefaultPtr
        ? ExportProperty(Property, DefaultPtr, DefaultExportOwner, bDefaultTruncated)
        : FString();

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("owner_path"), OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), OwnerKind);
    Row->SetStringField(TEXT("owner_type"), OwnerType);
    Row->SetNumberField(TEXT("property_index"), State.Rows);
    Row->SetNumberField(TEXT("depth"), Depth);
    Row->SetStringField(TEXT("declaring_type"), Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString());
    Row->SetStringField(TEXT("root_property"), RootProperty);
    Row->SetStringField(TEXT("property_name"), Property->GetName());
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
    Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
    Row->SetStringField(TEXT("value"), Value);
    Row->SetBoolField(TEXT("default_present"), DefaultPtr != nullptr);
    if (DefaultPtr)
    {
        Row->SetStringField(TEXT("default_value"), DefaultValue);
        Row->SetBoolField(TEXT("differs_from_default"), !Property->Identical(ValuePtr, DefaultPtr, PPF_None));
    }
    Row->SetBoolField(TEXT("truncated"), bTruncated || bDefaultTruncated);
    const int32 ElementCount = ContainerElementCount(Property, ValuePtr);
    if (ElementCount >= 0) Row->SetNumberField(TEXT("element_count"), ElementCount);
    if (!PropertyWriter.Write(Row)) return false;
    ++State.Rows;
    ++PropertyCount;
    if (bTruncated || bDefaultTruncated) ++Counts.TruncatedProperties;

    if (!WriteReference(
            Property, ValuePtr, AssetPath, OwnerPath, OwnerKind, OwnerType,
            RootProperty, PropertyPath, ReferenceWriter, ReferenceCount))
    {
        return false;
    }

    if (Depth >= MaxDepth)
    {
        if (CastField<FStructProperty>(Property) || CastField<FArrayProperty>(Property) ||
            CastField<FSetProperty>(Property) || CastField<FMapProperty>(Property))
        {
            ++Counts.PropertyDepthLimitHits;
        }
        return true;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        for (TFieldIterator<FProperty> It(StructProperty->Struct); It; ++It)
        {
            const FProperty* Child = *It;
            if (!ShouldInspectProperty(Child)) continue;
            for (int32 StaticIndex = 0; StaticIndex < Child->ArrayDim; ++StaticIndex)
            {
                const void* ChildPtr = Child->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const void* ChildDefaultPtr = DefaultPtr
                    ? Child->ContainerPtrToValuePtr<void>(DefaultPtr, StaticIndex)
                    : nullptr;
                FString ChildPath = PropertyPath + TEXT(".") + Child->GetName();
                if (Child->ArrayDim > 1)
                    ChildPath += FString::Printf(TEXT("[%d]"), StaticIndex);
                if (!WritePropertyRecursive(
                        Child, ChildPtr, ChildDefaultPtr, ExportOwner, DefaultExportOwner,
                        AssetPath, OwnerPath, OwnerKind, OwnerType, RootProperty, ChildPath,
                        Depth + 1, PropertyWriter, ReferenceWriter, State, Counts,
                        PropertyCount, ReferenceCount))
                {
                    return false;
                }
            }
        }
    }
    else if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, const_cast<void*>(ValuePtr));
        TUniquePtr<FScriptArrayHelper> DefaultHelper;
        if (DefaultPtr)
            DefaultHelper = MakeUnique<FScriptArrayHelper>(ArrayProperty, const_cast<void*>(DefaultPtr));
        const int32 Limit = FMath::Min(Helper.Num(), MaxContainerElements);
        if (Helper.Num() > Limit) ++Counts.ContainerElementLimitHits;
        for (int32 Index = 0; Index < Limit; ++Index)
        {
            const void* ElementPtr = Helper.GetRawPtr(Index);
            const void* ElementDefaultPtr = DefaultHelper.IsValid() && Index < DefaultHelper->Num()
                ? DefaultHelper->GetRawPtr(Index)
                : nullptr;
            if (!WritePropertyRecursive(
                    ArrayProperty->Inner, ElementPtr, ElementDefaultPtr, ExportOwner, DefaultExportOwner,
                    AssetPath, OwnerPath, OwnerKind, OwnerType, RootProperty,
                    FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                    Depth + 1, PropertyWriter, ReferenceWriter, State, Counts,
                    PropertyCount, ReferenceCount))
            {
                return false;
            }
        }
    }
    else if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, const_cast<void*>(ValuePtr));
        int32 Written = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Written < MaxContainerElements; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            if (!WritePropertyRecursive(
                    SetProperty->ElementProp, Helper.GetElementPtr(Index), nullptr,
                    ExportOwner, DefaultExportOwner, AssetPath, OwnerPath, OwnerKind, OwnerType,
                    RootProperty, FString::Printf(TEXT("%s{%d}"), *PropertyPath, Written),
                    Depth + 1, PropertyWriter, ReferenceWriter, State, Counts,
                    PropertyCount, ReferenceCount))
            {
                return false;
            }
            ++Written;
        }
        if (Helper.Num() > Written) ++Counts.ContainerElementLimitHits;
    }
    else if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, const_cast<void*>(ValuePtr));
        int32 Written = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Written < MaxContainerElements; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            if (!WritePropertyRecursive(
                    MapProperty->KeyProp, Helper.GetKeyPtr(Index), nullptr,
                    ExportOwner, DefaultExportOwner, AssetPath, OwnerPath, OwnerKind, OwnerType,
                    RootProperty, FString::Printf(TEXT("%s{%d}.Key"), *PropertyPath, Written),
                    Depth + 1, PropertyWriter, ReferenceWriter, State, Counts,
                    PropertyCount, ReferenceCount))
            {
                return false;
            }
            if (!WritePropertyRecursive(
                    MapProperty->ValueProp, Helper.GetValuePtr(Index), nullptr,
                    ExportOwner, DefaultExportOwner, AssetPath, OwnerPath, OwnerKind, OwnerType,
                    RootProperty, FString::Printf(TEXT("%s{%d}.Value"), *PropertyPath, Written),
                    Depth + 1, PropertyWriter, ReferenceWriter, State, Counts,
                    PropertyCount, ReferenceCount))
            {
                return false;
            }
            ++Written;
        }
        if (Helper.Num() > Written) ++Counts.ContainerElementLimitHits;
    }

    return true;
}

static bool WriteObjectProperties(
    UObject* Object,
    const FString& AssetPath,
    const FString& OwnerKind,
    FJsonlWriter& PropertyWriter,
    FJsonlWriter& ReferenceWriter,
    FCounts& Counts,
    int64& PropertyCount,
    int64& ReferenceCount)
{
    if (!Object) return true;
    UObject* DefaultObject = Object->GetClass()->GetDefaultObject(false);
    FOwnerState State;
    TSet<FString> Seen;
    for (TFieldIterator<FProperty> It(Object->GetClass()); It; ++It)
    {
        const FProperty* Property = *It;
        if (!ShouldInspectProperty(Property)) continue;
        const FString Key = (Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString()) +
            TEXT("::") + Property->GetName();
        if (Seen.Contains(Key)) continue;
        Seen.Add(Key);

        for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
        {
            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
            const void* DefaultPtr = DefaultObject
                ? Property->ContainerPtrToValuePtr<void>(DefaultObject, StaticIndex)
                : nullptr;
            FString PropertyPath = Property->GetName();
            if (Property->ArrayDim > 1)
                PropertyPath += FString::Printf(TEXT("[%d]"), StaticIndex);
            if (!WritePropertyRecursive(
                    Property, ValuePtr, DefaultPtr, Object, DefaultObject,
                    AssetPath, Object->GetPathName(), OwnerKind, Object->GetClass()->GetPathName(),
                    Property->GetName(), PropertyPath, 0,
                    PropertyWriter, ReferenceWriter, State, Counts,
                    PropertyCount, ReferenceCount))
            {
                return false;
            }
        }
    }
    return true;
}

static TArray<TSharedPtr<FJsonValue>> ClassHierarchy(UClass* Class)
{
    TArray<TSharedPtr<FJsonValue>> Values;
    for (UClass* Current = Class; Current; Current = Current->GetSuperClass())
        Values.Add(MakeShared<FJsonValueString>(Current->GetPathName()));
    return Values;
}

static FString PinDirectionName(ERigVMPinDirection Direction)
{
    if (const UEnum* Enum = StaticEnum<ERigVMPinDirection>())
        return Enum->GetNameStringByValue(static_cast<int64>(Direction));
    return FString::FromInt(static_cast<int32>(Direction));
}

static bool WritePinRecursive(
    const FString& AssetPath,
    const FString& GraphPath,
    const FString& NodePath,
    URigVMPin* Pin,
    int32 Depth,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Pin) return true;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("graph_path"), GraphPath);
    Row->SetStringField(TEXT("node_path"), NodePath);
    Row->SetStringField(TEXT("pin_path"), Pin->GetPinPath(true));
    Row->SetStringField(TEXT("pin_name"), Pin->GetName());
    Row->SetStringField(TEXT("direction"), PinDirectionName(Pin->GetDirection()));
    Row->SetNumberField(TEXT("depth"), Depth);
    Row->SetNumberField(TEXT("pin_index"), Pin->GetPinIndex());
    Row->SetStringField(TEXT("cpp_type"), Pin->GetCPPType());
    Row->SetStringField(TEXT("cpp_type_object"), Pin->GetCPPTypeObject() ? Pin->GetCPPTypeObject()->GetPathName() : FString());
    Row->SetStringField(TEXT("default_value"), Pin->GetDefaultValue());
    Row->SetStringField(TEXT("original_default_value"), Pin->GetOriginalDefaultValue());
    Row->SetBoolField(TEXT("has_default_override"), Pin->HasDefaultValueOverride());
    Row->SetNumberField(TEXT("subpin_count"), Pin->GetSubPins().Num());
    if (!Writers.Pins.Write(Row)) return false;
    ++Counts.RigVMPins;
    for (URigVMPin* Child : Pin->GetSubPins())
    {
        if (!WritePinRecursive(AssetPath, GraphPath, NodePath, Child, Depth + 1, Writers, Counts))
            return false;
    }
    return true;
}

static bool WriteGraph(
    const FString& AssetPath,
    URigVMGraph* Graph,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Graph) return true;
    const FString GraphPath = Graph->GetPathName();
    const TArray<URigVMNode*>& Nodes = Graph->GetNodes();
    const TArray<URigVMLink*>& Links = Graph->GetLinks();

    TSharedRef<FJsonObject> GraphRow = MakeShared<FJsonObject>();
    GraphRow->SetStringField(TEXT("asset_path"), AssetPath);
    GraphRow->SetStringField(TEXT("graph_path"), GraphPath);
    GraphRow->SetStringField(TEXT("graph_name"), Graph->GetGraphName());
    GraphRow->SetStringField(TEXT("graph_node_path"), Graph->GetNodePath());
    GraphRow->SetStringField(TEXT("graph_class"), Graph->GetClass()->GetPathName());
    GraphRow->SetStringField(TEXT("schema_class"), Graph->GetSchemaClass() ? Graph->GetSchemaClass()->GetPathName() : FString());
    GraphRow->SetStringField(TEXT("execute_context_struct"), Graph->GetExecuteContextStruct() ? Graph->GetExecuteContextStruct()->GetPathName() : FString());
    GraphRow->SetNumberField(TEXT("node_count"), Nodes.Num());
    GraphRow->SetNumberField(TEXT("link_count"), Links.Num());
    GraphRow->SetBoolField(TEXT("is_root_graph"), Graph->IsRootGraph());
    GraphRow->SetBoolField(TEXT("is_top_level_graph"), Graph->IsTopLevelGraph());
    if (!Writers.Graphs.Write(GraphRow)) return false;
    ++Counts.RigVMGraphs;

    for (URigVMNode* Node : Nodes)
    {
        if (!Node) continue;
        const FString NodePath = Node->GetNodePath(true);
        TSharedRef<FJsonObject> NodeRow = MakeShared<FJsonObject>();
        NodeRow->SetStringField(TEXT("asset_path"), AssetPath);
        NodeRow->SetStringField(TEXT("graph_path"), GraphPath);
        NodeRow->SetStringField(TEXT("node_path"), NodePath);
        NodeRow->SetStringField(TEXT("node_name"), Node->GetName());
        NodeRow->SetStringField(TEXT("node_class"), Node->GetClass()->GetPathName());
        NodeRow->SetNumberField(TEXT("node_index"), Node->GetNodeIndex());
        NodeRow->SetNumberField(TEXT("top_level_pin_count"), Node->GetPins().Num());
        if (URigVMUnitNode* UnitNode = Cast<URigVMUnitNode>(Node))
        {
            ++Counts.UnitNodes;
            NodeRow->SetStringField(TEXT("unit_script_struct"), UnitNode->GetScriptStruct() ? UnitNode->GetScriptStruct()->GetPathName() : FString());
            NodeRow->SetStringField(TEXT("method_name"), UnitNode->GetMethodName().ToString());
            NodeRow->SetStringField(TEXT("event_name"), UnitNode->GetEventName().ToString());
        }
        else
        {
            NodeRow->SetStringField(TEXT("unit_script_struct"), FString());
        }
        if (!Writers.Nodes.Write(NodeRow)) return false;
        ++Counts.RigVMNodes;

        for (URigVMPin* Pin : Node->GetPins())
        {
            if (!WritePinRecursive(AssetPath, GraphPath, NodePath, Pin, 0, Writers, Counts))
                return false;
        }
    }

    for (URigVMLink* Link : Links)
    {
        if (!Link) continue;
        URigVMPin* SourcePin = Link->GetSourcePin();
        URigVMPin* TargetPin = Link->GetTargetPin();
        TSharedRef<FJsonObject> LinkRow = MakeShared<FJsonObject>();
        LinkRow->SetStringField(TEXT("asset_path"), AssetPath);
        LinkRow->SetStringField(TEXT("graph_path"), GraphPath);
        LinkRow->SetStringField(TEXT("link_path"), Link->GetPathName());
        LinkRow->SetStringField(TEXT("source_pin_path"), SourcePin ? SourcePin->GetPinPath(true) : FString());
        LinkRow->SetStringField(TEXT("target_pin_path"), TargetPin ? TargetPin->GetPinPath(true) : FString());
        LinkRow->SetStringField(TEXT("source_node_path"), SourcePin && SourcePin->GetNode() ? SourcePin->GetNode()->GetNodePath(true) : FString());
        LinkRow->SetStringField(TEXT("target_node_path"), TargetPin && TargetPin->GetNode() ? TargetPin->GetNode()->GetNodePath(true) : FString());
        if (!Writers.Links.Write(LinkRow)) return false;
        ++Counts.RigVMLinks;
    }
    return true;
}

static bool IsRigVMModelObject(UObject* Object)
{
    return Object && (
        Object->IsA<URigVMGraph>() ||
        Object->IsA<URigVMNode>() ||
        Object->IsA<URigVMPin>() ||
        Object->IsA<URigVMLink>());
}

static FString SubobjectKind(UObject* Object)
{
    if (!Object) return TEXT("unknown");
    if (Object->IsA<URigVMGraph>()) return TEXT("rigvm_graph");
    if (Object->IsA<URigVMNode>()) return TEXT("rigvm_node");
    if (Object->IsA<URigVMPin>()) return TEXT("rigvm_pin");
    if (Object->IsA<URigVMLink>()) return TEXT("rigvm_link");
    const FString ClassPath = Object->GetClass()->GetPathName();
    if (ClassPath.StartsWith(TEXT("/Script/UAF")) || ClassPath.StartsWith(TEXT("/Script/AnimNext")))
        return TEXT("uaf_authored_object");
    return TEXT("other_subobject");
}

static bool WriteAsset(
    const FAssetData& AssetData,
    UObject* Asset,
    FWriters& Writers,
    FCounts& Counts,
    FString& OutError)
{
    if (!Asset) return false;
    const FString AssetPath = Asset->GetPathName();

    TSharedRef<FJsonObject> AssetRow = MakeShared<FJsonObject>();
    AssetRow->SetStringField(TEXT("asset_path"), AssetPath);
    AssetRow->SetStringField(TEXT("package_name"), AssetData.PackageName.ToString());
    AssetRow->SetStringField(TEXT("asset_name"), AssetData.AssetName.ToString());
    AssetRow->SetStringField(TEXT("registry_class"), AssetData.AssetClassPath.ToString());
    AssetRow->SetStringField(TEXT("loaded_class"), Asset->GetClass()->GetPathName());
    AssetRow->SetArrayField(TEXT("class_hierarchy"), ClassHierarchy(Asset->GetClass()));
    AssetRow->SetBoolField(TEXT("loaded"), true);
    if (!Writers.Assets.Write(AssetRow))
    {
        OutError = TEXT("failed writing UAF asset row: ") + AssetPath;
        return false;
    }
    ++Counts.LoadedAssets;

    if (!WriteObjectProperties(
            Asset, AssetPath, TEXT("asset"), Writers.AssetProperties, Writers.AssetReferences,
            Counts, Counts.AssetProperties, Counts.AssetReferences))
    {
        OutError = TEXT("failed reflecting UAF asset: ") + AssetPath;
        return false;
    }

    TArray<UObject*> Objects;
    GetObjectsWithOuter(Asset, Objects, true);
    Objects.Sort([](const UObject& A, const UObject& B)
    {
        return A.GetPathName() < B.GetPathName();
    });

    TSet<FString> SeenGraphs;
    for (UObject* Object : Objects)
    {
        if (!Object) continue;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetStringField(TEXT("object_path"), Object->GetPathName());
        Row->SetStringField(TEXT("outer_path"), Object->GetOuter() ? Object->GetOuter()->GetPathName() : FString());
        Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
        Row->SetStringField(TEXT("object_kind"), SubobjectKind(Object));
        Row->SetArrayField(TEXT("class_hierarchy"), ClassHierarchy(Object->GetClass()));
        if (!Writers.Subobjects.Write(Row))
        {
            OutError = TEXT("failed writing UAF subobject row: ") + Object->GetPathName();
            return false;
        }
        ++Counts.Subobjects;

        if (!IsRigVMModelObject(Object))
        {
            if (!WriteObjectProperties(
                    Object, AssetPath, TEXT("subobject"),
                    Writers.SubobjectProperties, Writers.SubobjectReferences,
                    Counts, Counts.SubobjectProperties, Counts.SubobjectReferences))
            {
                OutError = TEXT("failed reflecting UAF subobject: ") + Object->GetPathName();
                return false;
            }
        }

        if (URigVMGraph* Graph = Cast<URigVMGraph>(Object))
        {
            if (!SeenGraphs.Contains(Graph->GetPathName()))
            {
                SeenGraphs.Add(Graph->GetPathName());
                if (!WriteGraph(AssetPath, Graph, Writers, Counts))
                {
                    OutError = TEXT("failed writing UAF RigVM graph: ") + Graph->GetPathName();
                    return false;
                }
            }
        }
    }
    return true;
}

static bool WriteManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetBoolField(TEXT("diagnostic_only"), true);
    Root->SetBoolField(TEXT("semantic_promotion"), false);
    Root->SetBoolField(TEXT("schema_promotion"), false);
    Root->SetBoolField(TEXT("runtime_state_captured"), false);
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("capture_scope"), TEXT("installed UE UAF/UAFAnimGraph/UAFSharedAssets plugin content; authored/default state only"));

    TSharedRef<FJsonObject> CountObject = MakeShared<FJsonObject>();
    CountObject->SetNumberField(TEXT("registry_candidates"), Counts.RegistryCandidates);
    CountObject->SetNumberField(TEXT("loaded_assets"), Counts.LoadedAssets);
    CountObject->SetNumberField(TEXT("asset_properties"), Counts.AssetProperties);
    CountObject->SetNumberField(TEXT("asset_references"), Counts.AssetReferences);
    CountObject->SetNumberField(TEXT("subobjects"), Counts.Subobjects);
    CountObject->SetNumberField(TEXT("subobject_properties"), Counts.SubobjectProperties);
    CountObject->SetNumberField(TEXT("subobject_references"), Counts.SubobjectReferences);
    CountObject->SetNumberField(TEXT("rigvm_graphs"), Counts.RigVMGraphs);
    CountObject->SetNumberField(TEXT("rigvm_nodes"), Counts.RigVMNodes);
    CountObject->SetNumberField(TEXT("rigvm_pins"), Counts.RigVMPins);
    CountObject->SetNumberField(TEXT("rigvm_links"), Counts.RigVMLinks);
    CountObject->SetNumberField(TEXT("unit_nodes"), Counts.UnitNodes);
    CountObject->SetNumberField(TEXT("truncated_properties"), Counts.TruncatedProperties);
    CountObject->SetNumberField(TEXT("property_depth_limit_hits"), Counts.PropertyDepthLimitHits);
    CountObject->SetNumberField(TEXT("property_row_limit_hits"), Counts.PropertyRowLimitHits);
    CountObject->SetNumberField(TEXT("container_element_limit_hits"), Counts.ContainerElementLimitHits);
    Root->SetObjectField(TEXT("counts"), CountObject);

    TArray<TSharedPtr<FJsonValue>> Roots;
    for (const TCHAR* MountRoot : MountRoots)
        Roots.Add(MakeShared<FJsonValueString>(MountRoot));
    Root->SetArrayField(TEXT("mount_roots"), Roots);

    FString Text;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    return FFileHelper::SaveStringToFile(Text, *FPaths::Combine(OutputDir, TEXT("uaf_capture_manifest.json")), FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

} // namespace UnrealAssetToolUAF

UUnrealAssetToolUAFCommandlet::UUnrealAssetToolUAFCommandlet()
{
    IsClient = false;
    IsServer = false;
    IsEditor = true;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolUAFCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolUAF;

    FString OutputDir;
    if (!FParse::Value(*Params, TEXT("Output="), OutputDir) || OutputDir.IsEmpty())
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolUAF requires -Output=<directory>"));
        return 2;
    }
    OutputDir = FPaths::ConvertRelativePathToFull(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    FWriters Writers;
    FCounts Counts;
    FString Error;
    if (!Writers.Open(OutputDir))
    {
        Error = TEXT("failed opening one or more UAF capture output streams");
        WriteManifest(OutputDir, Counts, false, Error);
        UE_LOG(LogTemp, Error, TEXT("%s"), *Error);
        return 3;
    }

    FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.WaitForPremadeAssetRegistry();

    TArray<FString> Paths;
    for (const TCHAR* MountRoot : MountRoots)
        Paths.Add(MountRoot);
    Registry.ScanPathsSynchronous(Paths, true, true);
    Registry.WaitForCompletion();

    TMap<FString, FAssetData> Candidates;
    for (const TCHAR* MountRoot : MountRoots)
    {
        FARFilter Filter;
        Filter.PackagePaths.Add(*MountRoot);
        Filter.bRecursivePaths = true;
        TArray<FAssetData> Assets;
        Registry.GetAssets(Filter, Assets);
        for (const FAssetData& AssetData : Assets)
        {
            const FString ObjectPath = AssetData.GetSoftObjectPath().ToString();
            if (!ObjectPath.IsEmpty())
                Candidates.Add(ObjectPath, AssetData);
        }
    }

    TArray<FString> CandidatePaths;
    Candidates.GetKeys(CandidatePaths);
    CandidatePaths.Sort();
    Counts.RegistryCandidates = CandidatePaths.Num();

    for (const FString& ObjectPath : CandidatePaths)
    {
        const FAssetData* AssetData = Candidates.Find(ObjectPath);
        if (!AssetData) continue;
        UObject* Asset = StaticLoadObject(UObject::StaticClass(), nullptr, *ObjectPath);
        if (!Asset)
        {
            Error = TEXT("failed loading mounted UAF asset: ") + ObjectPath;
            Writers.Close();
            WriteManifest(OutputDir, Counts, false, Error);
            UE_LOG(LogTemp, Error, TEXT("%s"), *Error);
            return 4;
        }
        if (!WriteAsset(*AssetData, Asset, Writers, Counts, Error))
        {
            Writers.Close();
            WriteManifest(OutputDir, Counts, false, Error);
            UE_LOG(LogTemp, Error, TEXT("%s"), *Error);
            return 5;
        }
    }

    const bool bClosed = Writers.Close();
    if (!bClosed)
        Error = TEXT("failed closing one or more UAF capture output streams");
    const bool bSuccess = Error.IsEmpty() && Counts.RegistryCandidates > 0 && Counts.LoadedAssets == Counts.RegistryCandidates;
    if (!bSuccess && Error.IsEmpty())
        Error = TEXT("UAF capture loaded no representative mounted plugin assets");
    if (!WriteManifest(OutputDir, Counts, bSuccess, Error))
    {
        UE_LOG(LogTemp, Error, TEXT("failed writing UAF capture manifest"));
        return 6;
    }

    UE_LOG(LogTemp, Display, TEXT("UAF focused capture: candidates=%lld loaded=%lld graphs=%lld nodes=%lld pins=%lld links=%lld"),
        Counts.RegistryCandidates, Counts.LoadedAssets, Counts.RigVMGraphs, Counts.RigVMNodes, Counts.RigVMPins, Counts.RigVMLinks);
    if (!bSuccess)
    {
        UE_LOG(LogTemp, Error, TEXT("%s"), *Error);
        return 7;
    }
    return 0;
}
