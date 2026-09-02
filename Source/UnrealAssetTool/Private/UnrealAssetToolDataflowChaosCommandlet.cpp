#include "UnrealAssetToolDataflowChaosCommandlet.h"

#include "Dataflow/DataflowGraph.h"
#include "Dataflow/DataflowInputOutput.h"
#include "Dataflow/DataflowNode.h"
#include "Dataflow/DataflowObject.h"
#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/App.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/Package.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolDataflowChaos
{
constexpr int32 SchemaVersion = 1;
constexpr int32 MaxExportChars = 65536;
constexpr int32 MaxPropertyDepth = 16;
constexpr int32 MaxElementsPerContainer = 4096;
constexpr int32 MaxPropertyRowsPerOwner = 65536;

struct FCounts
{
    int64 FocusAssets = 0;
    int64 LoadedAssets = 0;
    int64 DataflowAssets = 0;
    int64 GeometryCollections = 0;
    int64 Graphs = 0;
    int64 Nodes = 0;
    int64 Pins = 0;
    int64 Edges = 0;
    int64 DisabledNodes = 0;
    int64 DataflowAssetProperties = 0;
    int64 DataflowAssetReferences = 0;
    int64 NodeProperties = 0;
    int64 NodeReferences = 0;
    int64 GeometryCollectionProperties = 0;
    int64 GeometryCollectionReferences = 0;
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
    FJsonlWriter Graphs;
    FJsonlWriter Nodes;
    FJsonlWriter Pins;
    FJsonlWriter Edges;
    FJsonlWriter DataflowAssetProperties;
    FJsonlWriter DataflowAssetReferences;
    FJsonlWriter NodeProperties;
    FJsonlWriter NodeReferences;
    FJsonlWriter GeometryCollectionProperties;
    FJsonlWriter GeometryCollectionReferences;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("dataflow_chaos_assets.jsonl"))) &&
            Graphs.Open(FPaths::Combine(OutputDir, TEXT("dataflow_graphs.jsonl"))) &&
            Nodes.Open(FPaths::Combine(OutputDir, TEXT("dataflow_nodes.jsonl"))) &&
            Pins.Open(FPaths::Combine(OutputDir, TEXT("dataflow_pins.jsonl"))) &&
            Edges.Open(FPaths::Combine(OutputDir, TEXT("dataflow_edges.jsonl"))) &&
            DataflowAssetProperties.Open(FPaths::Combine(OutputDir, TEXT("dataflow_asset_properties.jsonl"))) &&
            DataflowAssetReferences.Open(FPaths::Combine(OutputDir, TEXT("dataflow_asset_references.jsonl"))) &&
            NodeProperties.Open(FPaths::Combine(OutputDir, TEXT("dataflow_node_properties.jsonl"))) &&
            NodeReferences.Open(FPaths::Combine(OutputDir, TEXT("dataflow_node_references.jsonl"))) &&
            GeometryCollectionProperties.Open(FPaths::Combine(OutputDir, TEXT("geometry_collection_properties.jsonl"))) &&
            GeometryCollectionReferences.Open(FPaths::Combine(OutputDir, TEXT("geometry_collection_references.jsonl")));
    }

    bool Close()
    {
        bool bOk = true;
        bOk = Assets.Close() && bOk;
        bOk = Graphs.Close() && bOk;
        bOk = Nodes.Close() && bOk;
        bOk = Pins.Close() && bOk;
        bOk = Edges.Close() && bOk;
        bOk = DataflowAssetProperties.Close() && bOk;
        bOk = DataflowAssetReferences.Close() && bOk;
        bOk = NodeProperties.Close() && bOk;
        bOk = NodeReferences.Close() && bOk;
        bOk = GeometryCollectionProperties.Close() && bOk;
        bOk = GeometryCollectionReferences.Close() && bOk;
        return bOk;
    }
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

static FString ContainerKind(const FProperty* Property)
{
    if (CastField<FArrayProperty>(Property)) return TEXT("array");
    if (CastField<FSetProperty>(Property)) return TEXT("set");
    if (CastField<FMapProperty>(Property)) return TEXT("map");
    if (CastField<FStructProperty>(Property)) return TEXT("struct");
    if (CastField<FSoftObjectProperty>(Property)) return TEXT("soft_object");
    if (CastField<FObjectPropertyBase>(Property)) return TEXT("object");
    return TEXT("scalar");
}

struct FWalkContext
{
    FString SourcePath;
    FString OwnerId;
    FString OwnerKind;
    FString OwnerType;
    UObject* ExportOwner = nullptr;
    const void* DefaultContainer = nullptr;
    UObject* DefaultExportOwner = nullptr;
    FJsonlWriter* Properties = nullptr;
    FJsonlWriter* References = nullptr;
    FCounts* Counts = nullptr;
    int64* PropertyCounter = nullptr;
    int64* ReferenceCounter = nullptr;
    int32 Rows = 0;
    bool bFailed = false;
};

static void EmitReference(
    FWalkContext& Context,
    const FString& RootProperty,
    const FString& PropertyPath,
    const FString& ReferenceKind,
    const FString& TargetPath,
    const FString& TargetClass)
{
    if (!Context.References || !Context.Counts || !Context.ReferenceCounter || TargetPath.IsEmpty() || Context.bFailed) return;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("source_path"), Context.SourcePath);
    Row->SetStringField(TEXT("owner_id"), Context.OwnerId);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetStringField(TEXT("owner_type"), Context.OwnerType);
    Row->SetStringField(TEXT("root_property"), RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), ReferenceKind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (!Context.References->Write(Row))
    {
        Context.bFailed = true;
        return;
    }
    ++(*Context.ReferenceCounter);
}

static void EmitProperty(
    const FProperty* Property,
    const void* ValuePtr,
    const void* DefaultValuePtr,
    const FString& RootProperty,
    const FString& PropertyPath,
    int32 Depth,
    int32 ElementCount,
    FWalkContext& Context)
{
    if (!Context.Properties || !Context.Counts || !Context.PropertyCounter || !Property || Context.bFailed) return;
    if (Context.Rows >= MaxPropertyRowsPerOwner)
    {
        ++Context.Counts->PropertyRowLimitHits;
        return;
    }

    bool bTruncated = false;
    const FString Value = ExportProperty(Property, ValuePtr, Context.ExportOwner, bTruncated);
    bool bDefaultTruncated = false;
    const FString DefaultValue = DefaultValuePtr
        ? ExportProperty(Property, DefaultValuePtr, Context.DefaultExportOwner, bDefaultTruncated)
        : FString();

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("source_path"), Context.SourcePath);
    Row->SetStringField(TEXT("owner_id"), Context.OwnerId);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetStringField(TEXT("owner_type"), Context.OwnerType);
    Row->SetStringField(TEXT("declaring_type"),
        Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString());
    Row->SetStringField(TEXT("root_property"), RootProperty);
    Row->SetStringField(TEXT("property_name"), Property->GetName());
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
    Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
    Row->SetStringField(TEXT("container_kind"), ContainerKind(Property));
    Row->SetNumberField(TEXT("depth"), Depth);
    if (ElementCount >= 0) Row->SetNumberField(TEXT("element_count"), ElementCount);
    Row->SetStringField(TEXT("value"), Value);
    Row->SetBoolField(TEXT("default_present"), DefaultValuePtr != nullptr);
    if (DefaultValuePtr)
    {
        Row->SetStringField(TEXT("default_value"), DefaultValue);
        Row->SetBoolField(TEXT("differs_from_default"), !Property->Identical(ValuePtr, DefaultValuePtr, PPF_None));
    }
    Row->SetBoolField(TEXT("truncated"), bTruncated || bDefaultTruncated);
    Row->SetBoolField(TEXT("dataflow_input"), Property->HasMetaData(TEXT("DataflowInput")));
    Row->SetBoolField(TEXT("dataflow_output"), Property->HasMetaData(TEXT("DataflowOutput")));
    Row->SetBoolField(TEXT("dataflow_passthrough"), Property->HasMetaData(TEXT("DataflowPassthrough")));
    Row->SetBoolField(TEXT("dataflow_intrinsic"), Property->HasMetaData(TEXT("DataflowIntrinsic")));
    if (!Context.Properties->Write(Row))
    {
        Context.bFailed = true;
        return;
    }
    ++Context.Rows;
    ++(*Context.PropertyCounter);
    if (bTruncated || bDefaultTruncated) ++Context.Counts->TruncatedProperties;
}

static void WalkPropertyValue(
    const FProperty* Property,
    const void* ValuePtr,
    const void* DefaultValuePtr,
    const FString& RootProperty,
    const FString& PropertyPath,
    int32 Depth,
    FWalkContext& Context)
{
    if (!Property || !ValuePtr || Context.bFailed) return;
    if (Depth > MaxPropertyDepth)
    {
        ++Context.Counts->PropertyDepthLimitHits;
        return;
    }
    if (Context.Rows >= MaxPropertyRowsPerOwner)
    {
        ++Context.Counts->PropertyRowLimitHits;
        return;
    }

    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
        EmitProperty(Property, ValuePtr, DefaultValuePtr, RootProperty, PropertyPath, Depth, Helper.Num(), Context);
        TUniquePtr<FScriptArrayHelper> DefaultHolder;
        FScriptArrayHelper* DefaultHelper = nullptr;
        if (DefaultValuePtr)
        {
            DefaultHolder = MakeUnique<FScriptArrayHelper>(ArrayProperty, DefaultValuePtr);
            DefaultHelper = DefaultHolder.Get();
        }
        const int32 Limit = FMath::Min(Helper.Num(), MaxElementsPerContainer);
        if (Helper.Num() > Limit) ++Context.Counts->ContainerElementLimitHits;
        for (int32 Index = 0; Index < Limit && !Context.bFailed; ++Index)
        {
            const void* ChildDefault = DefaultHelper && Index < DefaultHelper->Num()
                ? DefaultHelper->GetRawPtr(Index) : nullptr;
            WalkPropertyValue(
                ArrayProperty->Inner,
                Helper.GetRawPtr(Index),
                ChildDefault,
                RootProperty,
                FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                Depth + 1,
                Context);
        }
        return;
    }

    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, ValuePtr);
        EmitProperty(Property, ValuePtr, DefaultValuePtr, RootProperty, PropertyPath, Depth, Helper.Num(), Context);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < MaxElementsPerContainer && !Context.bFailed; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            WalkPropertyValue(
                SetProperty->ElementProp,
                Helper.GetElementPtr(Index),
                nullptr,
                RootProperty,
                FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++),
                Depth + 1,
                Context);
        }
        if (Helper.Num() > Emitted) ++Context.Counts->ContainerElementLimitHits;
        return;
    }

    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, ValuePtr);
        EmitProperty(Property, ValuePtr, DefaultValuePtr, RootProperty, PropertyPath, Depth, Helper.Num(), Context);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < MaxElementsPerContainer && !Context.bFailed; ++Index)
        {
            if (!Helper.IsValidIndex(Index)) continue;
            const FString Base = FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++);
            WalkPropertyValue(MapProperty->KeyProp, Helper.GetKeyPtr(Index), nullptr, RootProperty, Base + TEXT(".key"), Depth + 1, Context);
            WalkPropertyValue(MapProperty->ValueProp, Helper.GetValuePtr(Index), nullptr, RootProperty, Base + TEXT(".value"), Depth + 1, Context);
        }
        if (Helper.Num() > Emitted) ++Context.Counts->ContainerElementLimitHits;
        return;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        EmitProperty(Property, ValuePtr, DefaultValuePtr, RootProperty, PropertyPath, Depth, -1, Context);
        if (!StructProperty->Struct) return;
        for (TFieldIterator<FProperty> It(StructProperty->Struct); It && !Context.bFailed; ++It)
        {
            const FProperty* Inner = *It;
            if (!ShouldInspectProperty(Inner)) continue;
            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim && !Context.bFailed; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const void* InnerDefault = DefaultValuePtr
                    ? Inner->ContainerPtrToValuePtr<void>(DefaultValuePtr, StaticIndex)
                    : nullptr;
                const FString ChildPath = PropertyPath + TEXT(".") + Inner->GetName() +
                    (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                WalkPropertyValue(Inner, InnerValue, InnerDefault, RootProperty, ChildPath, Depth + 1, Context);
            }
        }
        return;
    }

    EmitProperty(Property, ValuePtr, DefaultValuePtr, RootProperty, PropertyPath, Depth, -1, Context);

    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* SoftPtr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (SoftPtr && !SoftPtr->IsNull())
        {
            EmitReference(Context, RootProperty, PropertyPath, TEXT("soft_object"), SoftPtr->ToSoftObjectPath().ToString(), FString());
        }
        return;
    }

    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr);
        if (Target)
        {
            EmitReference(
                Context,
                RootProperty,
                PropertyPath,
                TEXT("hard_object"),
                Target->GetPathName(),
                Target->GetClass()->GetPathName());
        }
    }
}

static bool WalkStruct(
    const UStruct* Struct,
    void* Container,
    const void* DefaultContainer,
    FWalkContext& Context,
    const TSet<FName>* RootAllowList = nullptr)
{
    if (!Struct || !Container) return true;
    TSet<FString> Seen;
    for (TFieldIterator<FProperty> It(Struct); It && !Context.bFailed; ++It)
    {
        FProperty* Property = *It;
        if (!ShouldInspectProperty(Property)) continue;
        if (RootAllowList && !RootAllowList->Contains(Property->GetFName())) continue;
        const FString Key = (Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString()) +
            TEXT("::") + Property->GetName();
        if (Seen.Contains(Key)) continue;
        Seen.Add(Key);
        for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim && !Context.bFailed; ++StaticIndex)
        {
            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Container, StaticIndex);
            const void* DefaultPtr = DefaultContainer
                ? Property->ContainerPtrToValuePtr<void>(DefaultContainer, StaticIndex)
                : nullptr;
            const FString Root = Property->GetName();
            const FString Path = Root +
                (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
            WalkPropertyValue(Property, ValuePtr, DefaultPtr, Root, Path, 0, Context);
        }
    }
    return !Context.bFailed;
}

static FString GuidText(const FGuid& Guid)
{
    return Guid.ToString(EGuidFormats::DigitsWithHyphensLower);
}

static bool WritePin(
    const FString& AssetPath,
    const FGuid& NodeGuid,
    const TCHAR* Direction,
    const FDataflowConnection* Connection,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Connection) return true;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("node_guid"), GuidText(NodeGuid));
    Row->SetStringField(TEXT("pin_guid"), GuidText(Connection->GetGuid()));
    Row->SetStringField(TEXT("pin_name"), Connection->GetName().ToString());
    Row->SetStringField(TEXT("direction"), Direction);
    Row->SetStringField(TEXT("original_type"), Connection->GetOriginalType().ToString());
    Row->SetBoolField(TEXT("hidden"), Connection->GetPinIsHidden());
    const FProperty* Property = Connection->GetProperty();
    Row->SetStringField(TEXT("property_name"), Property ? Property->GetName() : FString());
    Row->SetStringField(TEXT("property_type"), Property ? Property->GetCPPType() : FString());
    if (!Writers.Pins.Write(Row)) return false;
    ++Counts.Pins;
    return true;
}

static bool WriteDataflow(UDataflow* DataflowAsset, FWriters& Writers, FCounts& Counts, FString& OutError)
{
    if (!DataflowAsset) return true;
    const FString AssetPath = DataflowAsset->GetPathName();
    ++Counts.DataflowAssets;

    static const TSet<FName> AssetRoots = {
        TEXT("Type"), TEXT("Variables"), TEXT("ReferenceAsset"), TEXT("Material")
    };
    FWalkContext AssetContext;
    AssetContext.SourcePath = AssetPath;
    AssetContext.OwnerId = AssetPath;
    AssetContext.OwnerKind = TEXT("dataflow_asset");
    AssetContext.OwnerType = DataflowAsset->GetClass()->GetPathName();
    AssetContext.ExportOwner = DataflowAsset;
    AssetContext.DefaultContainer = DataflowAsset->GetClass()->GetDefaultObject(false);
    AssetContext.DefaultExportOwner = Cast<UObject>(const_cast<void*>(AssetContext.DefaultContainer));
    AssetContext.Properties = &Writers.DataflowAssetProperties;
    AssetContext.References = &Writers.DataflowAssetReferences;
    AssetContext.Counts = &Counts;
    AssetContext.PropertyCounter = &Counts.DataflowAssetProperties;
    AssetContext.ReferenceCounter = &Counts.DataflowAssetReferences;
    if (!WalkStruct(DataflowAsset->GetClass(), DataflowAsset, AssetContext.DefaultContainer, AssetContext, &AssetRoots))
    {
        OutError = TEXT("failed reflecting UDataflow asset state: ") + AssetPath;
        return false;
    }

    const TSharedPtr<UE::Dataflow::FGraph> Graph = DataflowAsset->Dataflow;
    if (!Graph.IsValid())
    {
        OutError = TEXT("loaded UDataflow has no internal FGraph: ") + AssetPath;
        return false;
    }

    const auto& GraphNodes = Graph->GetNodes();
    const auto& GraphEdges = Graph->GetConnections();
    const TSet<FName>& Disabled = Graph->GetDisabledNodes();

    TSharedRef<FJsonObject> GraphRow = MakeShared<FJsonObject>();
    GraphRow->SetStringField(TEXT("asset_path"), AssetPath);
    GraphRow->SetStringField(TEXT("topology_guid"), GuidText(Graph->GetGraphTopologyGuid()));
    GraphRow->SetNumberField(TEXT("node_count"), GraphNodes.Num());
    GraphRow->SetNumberField(TEXT("edge_count"), GraphEdges.Num());
    GraphRow->SetNumberField(TEXT("disabled_node_count"), Disabled.Num());
    GraphRow->SetNumberField(TEXT("subgraph_count"), DataflowAsset->GetSubGraphs().Num());
    GraphRow->SetStringField(TEXT("provenance"), TEXT("loaded_udataflow_internal_fgraph"));
    if (!Writers.Graphs.Write(GraphRow))
    {
        OutError = TEXT("failed writing Dataflow graph row: ") + AssetPath;
        return false;
    }
    ++Counts.Graphs;

    for (const auto& Node : GraphNodes)
    {
        if (!Node.IsValid()) continue;
        const FGuid NodeGuid = Node->GetGuid();
        const FName NodeName = Node->GetName();
        const UScriptStruct* NodeStruct = Node->TypedScriptStruct();
        const bool bDisabled = Disabled.Contains(NodeName);

        TSharedRef<FJsonObject> NodeRow = MakeShared<FJsonObject>();
        NodeRow->SetStringField(TEXT("asset_path"), AssetPath);
        NodeRow->SetStringField(TEXT("node_guid"), GuidText(NodeGuid));
        NodeRow->SetStringField(TEXT("node_name"), NodeName.ToString());
        NodeRow->SetStringField(TEXT("node_struct"), NodeStruct ? NodeStruct->GetPathName() : FString());
        NodeRow->SetNumberField(TEXT("input_count"), Node->GetInputs().Num());
        NodeRow->SetNumberField(TEXT("output_count"), Node->GetOutputs().Num());
        NodeRow->SetBoolField(TEXT("disabled"), bDisabled);
        if (!Writers.Nodes.Write(NodeRow))
        {
            OutError = TEXT("failed writing Dataflow node row: ") + AssetPath;
            return false;
        }
        ++Counts.Nodes;
        if (bDisabled) ++Counts.DisabledNodes;

        for (FDataflowInput* Input : Node->GetInputs())
        {
            if (!WritePin(AssetPath, NodeGuid, TEXT("input"), Input, Writers, Counts))
            {
                OutError = TEXT("failed writing Dataflow input pin: ") + AssetPath;
                return false;
            }
        }
        for (FDataflowOutput* Output : Node->GetOutputs())
        {
            if (!WritePin(AssetPath, NodeGuid, TEXT("output"), Output, Writers, Counts))
            {
                OutError = TEXT("failed writing Dataflow output pin: ") + AssetPath;
                return false;
            }
        }

        if (NodeStruct)
        {
            FWalkContext NodeContext;
            NodeContext.SourcePath = AssetPath;
            NodeContext.OwnerId = GuidText(NodeGuid);
            NodeContext.OwnerKind = TEXT("dataflow_node");
            NodeContext.OwnerType = NodeStruct->GetPathName();
            NodeContext.ExportOwner = DataflowAsset;
            NodeContext.Properties = &Writers.NodeProperties;
            NodeContext.References = &Writers.NodeReferences;
            NodeContext.Counts = &Counts;
            NodeContext.PropertyCounter = &Counts.NodeProperties;
            NodeContext.ReferenceCounter = &Counts.NodeReferences;
            if (!WalkStruct(NodeStruct, Node.Get(), nullptr, NodeContext))
            {
                OutError = TEXT("failed reflecting Dataflow node state: ") + AssetPath + TEXT(" ") + GuidText(NodeGuid);
                return false;
            }
        }
    }

    for (const UE::Dataflow::FLink& Link : GraphEdges)
    {
        TSharedRef<FJsonObject> EdgeRow = MakeShared<FJsonObject>();
        EdgeRow->SetStringField(TEXT("asset_path"), AssetPath);
        EdgeRow->SetStringField(TEXT("source_node_guid"), GuidText(Link.OutputNode));
        EdgeRow->SetStringField(TEXT("source_pin_guid"), GuidText(Link.Output));
        EdgeRow->SetStringField(TEXT("target_node_guid"), GuidText(Link.InputNode));
        EdgeRow->SetStringField(TEXT("target_pin_guid"), GuidText(Link.Input));
        EdgeRow->SetStringField(TEXT("provenance"), TEXT("loaded_fgraph_link"));
        if (!Writers.Edges.Write(EdgeRow))
        {
            OutError = TEXT("failed writing Dataflow edge row: ") + AssetPath;
            return false;
        }
        ++Counts.Edges;
    }
    return true;
}

static bool WriteGeometryCollection(UObject* AssetObject, FWriters& Writers, FCounts& Counts, FString& OutError)
{
    if (!AssetObject) return true;
    const FString AssetPath = AssetObject->GetPathName();
    ++Counts.GeometryCollections;

    UObject* DefaultObject = AssetObject->GetClass()->GetDefaultObject(false);
    FWalkContext Context;
    Context.SourcePath = AssetPath;
    Context.OwnerId = AssetPath;
    Context.OwnerKind = TEXT("geometry_collection");
    Context.OwnerType = AssetObject->GetClass()->GetPathName();
    Context.ExportOwner = AssetObject;
    Context.DefaultContainer = DefaultObject;
    Context.DefaultExportOwner = DefaultObject;
    Context.Properties = &Writers.GeometryCollectionProperties;
    Context.References = &Writers.GeometryCollectionReferences;
    Context.Counts = &Counts;
    Context.PropertyCounter = &Counts.GeometryCollectionProperties;
    Context.ReferenceCounter = &Counts.GeometryCollectionReferences;
    if (!WalkStruct(AssetObject->GetClass(), AssetObject, DefaultObject, Context))
    {
        OutError = TEXT("failed reflecting Geometry Collection asset state: ") + AssetPath;
        return false;
    }
    return true;
}

static FString AssetKind(UObject* AssetObject)
{
    if (!AssetObject) return FString();
    const FString ClassPath = AssetObject->GetClass()->GetPathName();
    if (ClassPath == TEXT("/Script/DataflowEngine.Dataflow")) return TEXT("dataflow");
    if (ClassPath == TEXT("/Script/GeometryCollectionEngine.GeometryCollection")) return TEXT("geometry_collection");
    return FString();
}

static bool WriteAsset(
    const FString& AssetPath,
    UObject* AssetObject,
    FWriters& Writers,
    FCounts& Counts,
    FString& OutError)
{
    const FString Kind = AssetKind(AssetObject);
    TSharedRef<FJsonObject> AssetRow = MakeShared<FJsonObject>();
    AssetRow->SetStringField(TEXT("asset_path"), AssetPath);
    AssetRow->SetBoolField(TEXT("loaded"), AssetObject != nullptr);
    AssetRow->SetStringField(TEXT("loaded_class"), AssetObject ? AssetObject->GetClass()->GetPathName() : FString());
    AssetRow->SetStringField(TEXT("asset_kind"), Kind);
    AssetRow->SetStringField(TEXT("provenance"), TEXT("corpus_nominated_exact_asset_path_static_load"));
    if (!Writers.Assets.Write(AssetRow))
    {
        OutError = TEXT("failed writing Dataflow/Chaos focus asset row: ") + AssetPath;
        return false;
    }

    if (!AssetObject) return true;
    ++Counts.LoadedAssets;
    if (Kind == TEXT("dataflow"))
    {
        return WriteDataflow(Cast<UDataflow>(AssetObject), Writers, Counts, OutError);
    }
    if (Kind == TEXT("geometry_collection"))
    {
        return WriteGeometryCollection(AssetObject, Writers, Counts, OutError);
    }
    OutError = TEXT("focused asset loaded as unsupported class: ") + AssetPath + TEXT(" class=") + AssetObject->GetClass()->GetPathName();
    return false;
}

static bool WriteManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Root->SetStringField(TEXT("schema_name"), TEXT("dataflow_chaos_capture"));
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolDataflowChaos"));
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("project_name"), FApp::GetProjectName());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetBoolField(TEXT("diagnostic_only"), true);
    Root->SetBoolField(TEXT("semantic_promotion"), false);
    Root->SetBoolField(TEXT("schema_promotion"), false);
    Root->SetBoolField(TEXT("runtime_state_captured"), false);
    Root->SetStringField(
        TEXT("provenance"),
        TEXT("corpus_nominated_destruction_assets_plus_loaded_udataflow_fgraph_and_uobject_reflection"));

    TSharedRef<FJsonObject> CountsJson = MakeShared<FJsonObject>();
    CountsJson->SetNumberField(TEXT("focus_assets"), Counts.FocusAssets);
    CountsJson->SetNumberField(TEXT("loaded_assets"), Counts.LoadedAssets);
    CountsJson->SetNumberField(TEXT("dataflow_assets"), Counts.DataflowAssets);
    CountsJson->SetNumberField(TEXT("geometry_collections"), Counts.GeometryCollections);
    CountsJson->SetNumberField(TEXT("graphs"), Counts.Graphs);
    CountsJson->SetNumberField(TEXT("nodes"), Counts.Nodes);
    CountsJson->SetNumberField(TEXT("pins"), Counts.Pins);
    CountsJson->SetNumberField(TEXT("edges"), Counts.Edges);
    CountsJson->SetNumberField(TEXT("disabled_nodes"), Counts.DisabledNodes);
    CountsJson->SetNumberField(TEXT("dataflow_asset_properties"), Counts.DataflowAssetProperties);
    CountsJson->SetNumberField(TEXT("dataflow_asset_references"), Counts.DataflowAssetReferences);
    CountsJson->SetNumberField(TEXT("node_properties"), Counts.NodeProperties);
    CountsJson->SetNumberField(TEXT("node_references"), Counts.NodeReferences);
    CountsJson->SetNumberField(TEXT("geometry_collection_properties"), Counts.GeometryCollectionProperties);
    CountsJson->SetNumberField(TEXT("geometry_collection_references"), Counts.GeometryCollectionReferences);
    CountsJson->SetNumberField(TEXT("truncated_properties"), Counts.TruncatedProperties);
    CountsJson->SetNumberField(TEXT("property_depth_limit_hits"), Counts.PropertyDepthLimitHits);
    CountsJson->SetNumberField(TEXT("property_row_limit_hits"), Counts.PropertyRowLimitHits);
    CountsJson->SetNumberField(TEXT("container_element_limit_hits"), Counts.ContainerElementLimitHits);
    Root->SetObjectField(TEXT("counts"), CountsJson);

    static const TCHAR* FileNames[] = {
        TEXT("dataflow_chaos_assets.jsonl"),
        TEXT("dataflow_graphs.jsonl"),
        TEXT("dataflow_nodes.jsonl"),
        TEXT("dataflow_pins.jsonl"),
        TEXT("dataflow_edges.jsonl"),
        TEXT("dataflow_asset_properties.jsonl"),
        TEXT("dataflow_asset_references.jsonl"),
        TEXT("dataflow_node_properties.jsonl"),
        TEXT("dataflow_node_references.jsonl"),
        TEXT("geometry_collection_properties.jsonl"),
        TEXT("geometry_collection_references.jsonl"),
    };
    TArray<TSharedPtr<FJsonValue>> Files;
    for (const TCHAR* Name : FileNames) Files.Add(MakeShared<FJsonValueString>(Name));
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    Text.AppendChar(TEXT('\n'));
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("dataflow_chaos_capture_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}
} // namespace UnrealAssetToolDataflowChaos

UUnrealAssetToolDataflowChaosCommandlet::UUnrealAssetToolDataflowChaosCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolDataflowChaosCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolDataflowChaos;

    FString OutputDir;
    if (!FParse::Value(*Params, TEXT("Output="), OutputDir))
    {
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool/dataflow-chaos-capture"));
    }
    OutputDir = FPaths::ConvertRelativePathToFull(OutputDir);
    FPaths::NormalizeDirectoryName(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    FString FocusFile;
    if (!FParse::Value(*Params, TEXT("FocusFile="), FocusFile) || FocusFile.IsEmpty())
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolDataflowChaos requires -FocusFile=<path>"));
        return 2;
    }
    FocusFile = FPaths::ConvertRelativePathToFull(FocusFile);

    TArray<FString> FocusAssets;
    if (!FFileHelper::LoadFileToStringArray(FocusAssets, *FocusFile))
    {
        UE_LOG(LogTemp, Error, TEXT("Could not read Dataflow/Chaos focus file: %s"), *FocusFile);
        return 3;
    }
    FocusAssets.RemoveAll([](const FString& Value) { return Value.TrimStartAndEnd().IsEmpty(); });
    for (FString& Value : FocusAssets) Value = Value.TrimStartAndEnd();
    FocusAssets.Sort();
    TArray<FString> UniqueAssets;
    for (const FString& Value : FocusAssets)
    {
        if (UniqueAssets.IsEmpty() || UniqueAssets.Last() != Value) UniqueAssets.Add(Value);
    }
    FocusAssets = MoveTemp(UniqueAssets);

    FWriters Writers;
    FCounts Counts;
    Counts.FocusAssets = FocusAssets.Num();
    FString Error;
    bool bSuccess = Writers.Open(OutputDir);
    if (!bSuccess) Error = TEXT("could not open one or more Dataflow/Chaos capture JSONL writers");

    if (bSuccess)
    {
        for (const FString& AssetPath : FocusAssets)
        {
            UObject* AssetObject = StaticLoadObject(UObject::StaticClass(), nullptr, *AssetPath);
            if (!WriteAsset(AssetPath, AssetObject, Writers, Counts, Error))
            {
                bSuccess = false;
                break;
            }
        }
    }

    if (!Writers.Close())
    {
        bSuccess = false;
        if (Error.IsEmpty()) Error = TEXT("failed to finalize one or more Dataflow/Chaos capture JSONL writers");
    }
    if (!WriteManifest(OutputDir, Counts, bSuccess, Error))
    {
        UE_LOG(LogTemp, Error, TEXT("Failed to write Dataflow/Chaos capture manifest"));
        return 4;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolDataflowChaos: success=%s focus=%lld loaded=%lld dataflows=%lld geometry_collections=%lld graphs=%lld nodes=%lld pins=%lld edges=%lld node_properties=%lld gc_properties=%lld"),
        bSuccess ? TEXT("true") : TEXT("false"),
        Counts.FocusAssets,
        Counts.LoadedAssets,
        Counts.DataflowAssets,
        Counts.GeometryCollections,
        Counts.Graphs,
        Counts.Nodes,
        Counts.Pins,
        Counts.Edges,
        Counts.NodeProperties,
        Counts.GeometryCollectionProperties);
    return bSuccess ? 0 : 5;
}
