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
#include "UObject/SoftObjectPtr.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolDataflowChaos
{
constexpr int32 SchemaVersion = 1;
constexpr int32 MaxExportChars = 65536;
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
    int64 DataflowAssetProperties = 0;
    int64 DataflowAssetReferences = 0;
    int64 NodeProperties = 0;
    int64 NodeReferences = 0;
    int64 GeometryCollectionProperties = 0;
    int64 GeometryCollectionReferences = 0;
    int64 TruncatedProperties = 0;
    int64 PropertyRowLimitHits = 0;
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

static bool WriteDirectReference(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& SourcePath,
    const FString& OwnerId,
    const FString& OwnerKind,
    const FString& OwnerType,
    const FString& PropertyPath,
    FJsonlWriter& ReferenceWriter,
    int64& ReferenceCount)
{
    FString TargetPath;
    FString TargetClass;
    FString ReferenceKind;

    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* SoftPtr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (SoftPtr && !SoftPtr->IsNull())
        {
            TargetPath = SoftPtr->ToSoftObjectPath().ToString();
            ReferenceKind = TEXT("soft_object");
        }
    }
    else if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        if (UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr))
        {
            TargetPath = Target->GetPathName();
            TargetClass = Target->GetClass()->GetPathName();
            ReferenceKind = TEXT("hard_object");
        }
    }

    if (TargetPath.IsEmpty()) return true;

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("source_path"), SourcePath);
    Row->SetStringField(TEXT("owner_id"), OwnerId);
    Row->SetStringField(TEXT("owner_kind"), OwnerKind);
    Row->SetStringField(TEXT("owner_type"), OwnerType);
    Row->SetStringField(TEXT("root_property"), Property->GetName());
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), ReferenceKind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (!ReferenceWriter.Write(Row)) return false;
    ++ReferenceCount;
    return true;
}

static bool WriteTopLevelProperties(
    const UStruct* Struct,
    void* Container,
    const void* DefaultContainer,
    UObject* ExportOwner,
    UObject* DefaultExportOwner,
    const FString& SourcePath,
    const FString& OwnerId,
    const FString& OwnerKind,
    const FString& OwnerType,
    FJsonlWriter& PropertyWriter,
    FJsonlWriter& ReferenceWriter,
    FCounts& Counts,
    int64& PropertyCount,
    int64& ReferenceCount)
{
    if (!Struct || !Container) return true;
    int32 Rows = 0;
    TSet<FString> Seen;
    for (TFieldIterator<FProperty> It(Struct); It; ++It)
    {
        FProperty* Property = *It;
        if (!ShouldInspectProperty(Property)) continue;
        const FString Key = (Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString()) +
            TEXT("::") + Property->GetName();
        if (Seen.Contains(Key)) continue;
        Seen.Add(Key);

        for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
        {
            if (Rows >= MaxPropertyRowsPerOwner)
            {
                ++Counts.PropertyRowLimitHits;
                return true;
            }
            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Container, StaticIndex);
            const void* DefaultPtr = DefaultContainer
                ? Property->ContainerPtrToValuePtr<void>(DefaultContainer, StaticIndex)
                : nullptr;
            const FString PropertyPath = Property->GetName() +
                (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());

            bool bTruncated = false;
            const FString Value = ExportProperty(Property, ValuePtr, ExportOwner, bTruncated);
            bool bDefaultTruncated = false;
            const FString DefaultValue = DefaultPtr
                ? ExportProperty(Property, DefaultPtr, DefaultExportOwner, bDefaultTruncated)
                : FString();

            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("source_path"), SourcePath);
            Row->SetStringField(TEXT("owner_id"), OwnerId);
            Row->SetStringField(TEXT("owner_kind"), OwnerKind);
            Row->SetStringField(TEXT("owner_type"), OwnerType);
            Row->SetStringField(TEXT("declaring_type"),
                Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString());
            Row->SetStringField(TEXT("root_property"), Property->GetName());
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
            Row->SetBoolField(TEXT("dataflow_input"), Property->HasMetaData(TEXT("DataflowInput")));
            Row->SetBoolField(TEXT("dataflow_output"), Property->HasMetaData(TEXT("DataflowOutput")));
            Row->SetBoolField(TEXT("dataflow_passthrough"), Property->HasMetaData(TEXT("DataflowPassthrough")));
            Row->SetBoolField(TEXT("dataflow_intrinsic"), Property->HasMetaData(TEXT("DataflowIntrinsic")));
            if (!PropertyWriter.Write(Row)) return false;
            ++Rows;
            ++PropertyCount;
            if (bTruncated || bDefaultTruncated) ++Counts.TruncatedProperties;

            if (!WriteDirectReference(
                    Property,
                    ValuePtr,
                    SourcePath,
                    OwnerId,
                    OwnerKind,
                    OwnerType,
                    PropertyPath,
                    ReferenceWriter,
                    ReferenceCount))
            {
                return false;
            }
        }
    }
    return true;
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

    UObject* DefaultObject = DataflowAsset->GetClass()->GetDefaultObject(false);
    if (!WriteTopLevelProperties(
            DataflowAsset->GetClass(),
            DataflowAsset,
            DefaultObject,
            DataflowAsset,
            DefaultObject,
            AssetPath,
            AssetPath,
            TEXT("dataflow_asset"),
            DataflowAsset->GetClass()->GetPathName(),
            Writers.DataflowAssetProperties,
            Writers.DataflowAssetReferences,
            Counts,
            Counts.DataflowAssetProperties,
            Counts.DataflowAssetReferences))
    {
        OutError = TEXT("failed reflecting UDataflow asset state: ") + AssetPath;
        return false;
    }

    const auto Graph = DataflowAsset->GetDataflow();
    if (!Graph.IsValid())
    {
        OutError = TEXT("loaded UDataflow has no internal FGraph: ") + AssetPath;
        return false;
    }

    const auto& GraphNodes = Graph->GetNodes();
    const auto& GraphEdges = Graph->GetConnections();

    TSharedRef<FJsonObject> GraphRow = MakeShared<FJsonObject>();
    GraphRow->SetStringField(TEXT("asset_path"), AssetPath);
    GraphRow->SetNumberField(TEXT("node_count"), GraphNodes.Num());
    GraphRow->SetNumberField(TEXT("edge_count"), GraphEdges.Num());
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
        const UScriptStruct* NodeStruct = Node->TypedScriptStruct();

        TSharedRef<FJsonObject> NodeRow = MakeShared<FJsonObject>();
        NodeRow->SetStringField(TEXT("asset_path"), AssetPath);
        NodeRow->SetStringField(TEXT("node_guid"), GuidText(NodeGuid));
        NodeRow->SetStringField(TEXT("node_name"), Node->GetName().ToString());
        NodeRow->SetStringField(TEXT("node_struct"), NodeStruct ? NodeStruct->GetPathName() : FString());
        NodeRow->SetNumberField(TEXT("input_count"), Node->GetInputs().Num());
        NodeRow->SetNumberField(TEXT("output_count"), Node->GetOutputs().Num());
        if (!Writers.Nodes.Write(NodeRow))
        {
            OutError = TEXT("failed writing Dataflow node row: ") + AssetPath;
            return false;
        }
        ++Counts.Nodes;

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

        if (NodeStruct && !WriteTopLevelProperties(
                NodeStruct,
                Node.Get(),
                nullptr,
                DataflowAsset,
                nullptr,
                AssetPath,
                GuidText(NodeGuid),
                TEXT("dataflow_node"),
                NodeStruct->GetPathName(),
                Writers.NodeProperties,
                Writers.NodeReferences,
                Counts,
                Counts.NodeProperties,
                Counts.NodeReferences))
        {
            OutError = TEXT("failed reflecting Dataflow node state: ") + AssetPath + TEXT(" ") + GuidText(NodeGuid);
            return false;
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
    if (!WriteTopLevelProperties(
            AssetObject->GetClass(),
            AssetObject,
            DefaultObject,
            AssetObject,
            DefaultObject,
            AssetPath,
            AssetPath,
            TEXT("geometry_collection"),
            AssetObject->GetClass()->GetPathName(),
            Writers.GeometryCollectionProperties,
            Writers.GeometryCollectionReferences,
            Counts,
            Counts.GeometryCollectionProperties,
            Counts.GeometryCollectionReferences))
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
    CountsJson->SetNumberField(TEXT("disabled_nodes"), 0);
    CountsJson->SetNumberField(TEXT("dataflow_asset_properties"), Counts.DataflowAssetProperties);
    CountsJson->SetNumberField(TEXT("dataflow_asset_references"), Counts.DataflowAssetReferences);
    CountsJson->SetNumberField(TEXT("node_properties"), Counts.NodeProperties);
    CountsJson->SetNumberField(TEXT("node_references"), Counts.NodeReferences);
    CountsJson->SetNumberField(TEXT("geometry_collection_properties"), Counts.GeometryCollectionProperties);
    CountsJson->SetNumberField(TEXT("geometry_collection_references"), Counts.GeometryCollectionReferences);
    CountsJson->SetNumberField(TEXT("truncated_properties"), Counts.TruncatedProperties);
    CountsJson->SetNumberField(TEXT("property_depth_limit_hits"), 0);
    CountsJson->SetNumberField(TEXT("property_row_limit_hits"), Counts.PropertyRowLimitHits);
    CountsJson->SetNumberField(TEXT("container_element_limit_hits"), 0);
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
