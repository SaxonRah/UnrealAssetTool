struct FDataflowChaosCounts
{
    int64 Candidates = 0;
    int64 ScopedCandidates = 0;
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

struct FDataflowChaosWriters
{
    FJsonlWriter Graphs;
    FJsonlWriter Nodes;
    FJsonlWriter Pins;
    FJsonlWriter Edges;
    FJsonlWriter DataflowAssetProperties;
    FJsonlWriter DataflowAssetReferences;
    FJsonlWriter NodeProperties;
    FJsonlWriter NodeReferences;
    FJsonlWriter GeometryCollections;
    FJsonlWriter GeometryCollectionProperties;
    FJsonlWriter GeometryCollectionReferences;

    bool Open(const FString& OutputDir)
    {
        return Graphs.Open(FPaths::Combine(OutputDir, TEXT("dataflow_graphs.jsonl"))) &&
            Nodes.Open(FPaths::Combine(OutputDir, TEXT("dataflow_nodes.jsonl"))) &&
            Pins.Open(FPaths::Combine(OutputDir, TEXT("dataflow_pins.jsonl"))) &&
            Edges.Open(FPaths::Combine(OutputDir, TEXT("dataflow_edges.jsonl"))) &&
            DataflowAssetProperties.Open(FPaths::Combine(OutputDir, TEXT("dataflow_asset_properties.jsonl"))) &&
            DataflowAssetReferences.Open(FPaths::Combine(OutputDir, TEXT("dataflow_asset_references.jsonl"))) &&
            NodeProperties.Open(FPaths::Combine(OutputDir, TEXT("dataflow_node_properties.jsonl"))) &&
            NodeReferences.Open(FPaths::Combine(OutputDir, TEXT("dataflow_node_references.jsonl"))) &&
            GeometryCollections.Open(FPaths::Combine(OutputDir, TEXT("geometry_collections.jsonl"))) &&
            GeometryCollectionProperties.Open(FPaths::Combine(OutputDir, TEXT("geometry_collection_properties.jsonl"))) &&
            GeometryCollectionReferences.Open(FPaths::Combine(OutputDir, TEXT("geometry_collection_references.jsonl")));
    }
};

static FDataflowChaosCounts GDataflowChaosCounts;
static FDataflowChaosWriters GDataflowChaosWriters;
static constexpr int32 DataflowChaosMaxPropertyRowsPerOwner = 65536;

static const TSet<FName>& DataflowChaosGeometryCollectionBehaviorRoots()
{
    static const TSet<FName> Roots = {
        TEXT("EnableClustering"),
        TEXT("ClusterGroupIndex"),
        TEXT("MaxClusterLevel"),
        TEXT("DamageModel"),
        TEXT("DamageThreshold"),
        TEXT("bUseSizeSpecificDamageThreshold"),
        TEXT("bUseMaterialDamageModifiers"),
        TEXT("PerClusterOnlyDamageThreshold"),
        TEXT("DamagePropagationData"),
        TEXT("ClusterConnectionType"),
        TEXT("ConnectionGraphBoundsFilteringMargin"),
        TEXT("Mass"),
        TEXT("MinimumMassClamp"),
        TEXT("bMassAsDensity"),
        TEXT("bDensityFromPhysicsMaterial"),
        TEXT("PhysicsMaterial"),
        TEXT("MaximumSleepTime"),
        TEXT("SlowMovingVelocityThreshold"),
        TEXT("bSlowMovingAsSleeping"),
        TEXT("bRemoveOnMaxSleep"),
        TEXT("RemovalDuration"),
        TEXT("bScaleOnRemoval"),
        TEXT("bAutomaticCrumblePartialClusters"),
        TEXT("bOptimizeConvexes"),
        TEXT("SizeSpecificData"),
        TEXT("DataflowAsset"),
        TEXT("DataflowInstance"),
        TEXT("Overrides")
    };
    return Roots;
}

static FString DataflowChaosGuidText(const FGuid& Guid)
{
    return Guid.ToString(EGuidFormats::DigitsWithHyphensLower);
}

static FString DataflowChaosContainerKind(const FProperty* Property)
{
    if (CastField<FArrayProperty>(Property)) return TEXT("array");
    if (CastField<FSetProperty>(Property)) return TEXT("set");
    if (CastField<FMapProperty>(Property)) return TEXT("map");
    if (CastField<FStructProperty>(Property)) return TEXT("struct");
    if (CastField<FSoftObjectProperty>(Property)) return TEXT("soft_object");
    if (CastField<FObjectPropertyBase>(Property)) return TEXT("object");
    return TEXT("scalar");
}

static bool DataflowChaosWriteReference(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& SourcePath,
    const FString& OwnerId,
    const FString& OwnerKind,
    const FString& OwnerType,
    const FString& RootProperty,
    const FString& PropertyPath,
    FJsonlWriter& Writer,
    int64& Counter)
{
    if (!Property || !ValuePtr) return true;

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
        UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr);
        if (Target)
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
    Row->SetStringField(TEXT("root_property"), RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), ReferenceKind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (!Writer.Write(Row)) return false;
    ++Counter;
    return true;
}

static bool DataflowChaosWriteProperties(
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
    int64& PropertyCounter,
    int64& ReferenceCounter,
    const TSet<FName>* RootAllowList = nullptr)
{
    if (!Struct || !Container) return true;
    int32 PropertyIndex = 0;
    TSet<FString> Seen;
    for (TFieldIterator<FProperty> It(Struct); It; ++It)
    {
        FProperty* Property = *It;
        if (!ShouldInspectProperty(Property)) continue;
        if (RootAllowList && !RootAllowList->Contains(Property->GetFName())) continue;
        const FString Key = (Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString()) +
            TEXT("::") + Property->GetName();
        if (Seen.Contains(Key)) continue;
        Seen.Add(Key);

        for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
        {
            if (PropertyIndex >= DataflowChaosMaxPropertyRowsPerOwner)
            {
                ++GDataflowChaosCounts.PropertyRowLimitHits;
                return true;
            }
            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Container, StaticIndex);
            const void* DefaultPtr = DefaultContainer
                ? Property->ContainerPtrToValuePtr<void>(DefaultContainer, StaticIndex)
                : nullptr;
            const FString Root = Property->GetName();
            const FString Path = Root +
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
            Row->SetNumberField(TEXT("property_index"), PropertyIndex++);
            Row->SetStringField(TEXT("declaring_type"),
                Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString());
            Row->SetStringField(TEXT("root_property"), Root);
            Row->SetStringField(TEXT("property_name"), Property->GetName());
            Row->SetStringField(TEXT("property_path"), Path);
            Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
            Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
            Row->SetStringField(TEXT("container_kind"), DataflowChaosContainerKind(Property));
            Row->SetStringField(TEXT("value"), Value);
            Row->SetStringField(TEXT("default_value"), DefaultValue);
            Row->SetBoolField(TEXT("default_present"), DefaultPtr != nullptr);
            Row->SetBoolField(TEXT("differs_from_default"), DefaultPtr ? !Property->Identical(ValuePtr, DefaultPtr, PPF_None) : true);
            Row->SetBoolField(TEXT("truncated"), bTruncated || bDefaultTruncated);
            Row->SetBoolField(TEXT("dataflow_input"), Property->HasMetaData(TEXT("DataflowInput")));
            Row->SetBoolField(TEXT("dataflow_output"), Property->HasMetaData(TEXT("DataflowOutput")));
            Row->SetBoolField(TEXT("dataflow_passthrough"), Property->HasMetaData(TEXT("DataflowPassthrough")));
            Row->SetBoolField(TEXT("dataflow_intrinsic"), Property->HasMetaData(TEXT("DataflowIntrinsic")));
            if (!PropertyWriter.Write(Row)) return false;
            ++PropertyCounter;
            if (bTruncated || bDefaultTruncated) ++GDataflowChaosCounts.TruncatedProperties;

            if (!DataflowChaosWriteReference(
                    Property,
                    ValuePtr,
                    SourcePath,
                    OwnerId,
                    OwnerKind,
                    OwnerType,
                    Root,
                    Path,
                    ReferenceWriter,
                    ReferenceCounter))
            {
                return false;
            }
        }
    }
    return true;
}

static FString DataflowChaosObjectPropertyPath(UObject* Object, const FName PropertyName)
{
    if (!Object) return FString();
    const FObjectPropertyBase* Property = CastField<FObjectPropertyBase>(Object->GetClass()->FindPropertyByName(PropertyName));
    if (!Property) return FString();
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    UObject* Target = ValuePtr ? Property->GetObjectPropertyValue(ValuePtr) : nullptr;
    return Target ? Target->GetPathName() : FString();
}

static FString DataflowChaosNestedField(UObject* Object, const FName RootProperty, const FName NestedProperty)
{
    if (!Object) return FString();
    const FStructProperty* Root = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(RootProperty));
    if (!Root || !Root->Struct) return FString();
    const void* StructValue = Root->ContainerPtrToValuePtr<void>(Object);
    if (!StructValue) return FString();
    const FProperty* Nested = Root->Struct->FindPropertyByName(NestedProperty);
    if (!Nested) return FString();
    bool bTruncated = false;
    return ExportProperty(Nested, Nested->ContainerPtrToValuePtr<void>(StructValue), Object, bTruncated);
}

static bool DataflowChaosWritePin(
    const FString& AssetPath,
    const FGuid& NodeGuid,
    const TCHAR* Direction,
    int32 PinIndex,
    const FDataflowConnection* Connection)
{
    if (!Connection) return true;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("node_guid"), DataflowChaosGuidText(NodeGuid));
    Row->SetStringField(TEXT("pin_guid"), DataflowChaosGuidText(Connection->GetGuid()));
    Row->SetStringField(TEXT("pin_name"), Connection->GetName().ToString());
    Row->SetStringField(TEXT("direction"), Direction);
    Row->SetNumberField(TEXT("pin_index"), PinIndex);
    Row->SetStringField(TEXT("original_type"), Connection->GetOriginalType().ToString());
    const FProperty* Property = Connection->GetProperty();
    Row->SetStringField(TEXT("property_name"), Property ? Property->GetName() : FString());
    Row->SetStringField(TEXT("property_type"), Property ? Property->GetCPPType() : FString());
    if (!GDataflowChaosWriters.Pins.Write(Row)) return false;
    ++GDataflowChaosCounts.Pins;
    return true;
}

static bool DataflowChaosWriteDataflow(UDataflow* DataflowAsset, FString& OutError)
{
    if (!DataflowAsset) return true;
    const FString AssetPath = DataflowAsset->GetPathName();
    ++GDataflowChaosCounts.DataflowAssets;

    const int64 AssetPropertyStart = GDataflowChaosCounts.DataflowAssetProperties;
    const int64 AssetReferenceStart = GDataflowChaosCounts.DataflowAssetReferences;
    UObject* DefaultObject = DataflowAsset->GetClass()->GetDefaultObject(false);
    if (!DataflowChaosWriteProperties(
            DataflowAsset->GetClass(),
            DataflowAsset,
            DefaultObject,
            DataflowAsset,
            DefaultObject,
            AssetPath,
            AssetPath,
            TEXT("dataflow_asset"),
            DataflowAsset->GetClass()->GetPathName(),
            GDataflowChaosWriters.DataflowAssetProperties,
            GDataflowChaosWriters.DataflowAssetReferences,
            GDataflowChaosCounts.DataflowAssetProperties,
            GDataflowChaosCounts.DataflowAssetReferences))
    {
        OutError = TEXT("failed reflecting canonical UDataflow asset properties: ") + AssetPath;
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

    for (const auto& Node : GraphNodes)
    {
        if (!Node.IsValid()) continue;
        const FGuid NodeGuid = Node->GetGuid();
        const FString NodeGuidText = DataflowChaosGuidText(NodeGuid);
        const UScriptStruct* NodeStruct = Node->TypedScriptStruct();
        const int64 PropertyStart = GDataflowChaosCounts.NodeProperties;
        const int64 ReferenceStart = GDataflowChaosCounts.NodeReferences;
        if (NodeStruct && !DataflowChaosWriteProperties(
                NodeStruct,
                Node.Get(),
                nullptr,
                DataflowAsset,
                nullptr,
                AssetPath,
                NodeGuidText,
                TEXT("dataflow_node"),
                NodeStruct->GetPathName(),
                GDataflowChaosWriters.NodeProperties,
                GDataflowChaosWriters.NodeReferences,
                GDataflowChaosCounts.NodeProperties,
                GDataflowChaosCounts.NodeReferences))
        {
            OutError = TEXT("failed reflecting canonical Dataflow node properties: ") + AssetPath + TEXT(" ") + NodeGuidText;
            return false;
        }

        TSharedRef<FJsonObject> NodeRow = MakeShared<FJsonObject>();
        NodeRow->SetStringField(TEXT("asset_path"), AssetPath);
        NodeRow->SetStringField(TEXT("node_guid"), NodeGuidText);
        NodeRow->SetStringField(TEXT("node_name"), Node->GetName().ToString());
        NodeRow->SetStringField(TEXT("node_struct"), NodeStruct ? NodeStruct->GetPathName() : FString());
        NodeRow->SetNumberField(TEXT("input_count"), Node->GetInputs().Num());
        NodeRow->SetNumberField(TEXT("output_count"), Node->GetOutputs().Num());
        NodeRow->SetNumberField(TEXT("property_count"), GDataflowChaosCounts.NodeProperties - PropertyStart);
        NodeRow->SetNumberField(TEXT("reference_count"), GDataflowChaosCounts.NodeReferences - ReferenceStart);
        if (!GDataflowChaosWriters.Nodes.Write(NodeRow))
        {
            OutError = TEXT("failed writing canonical Dataflow node row: ") + AssetPath;
            return false;
        }
        ++GDataflowChaosCounts.Nodes;

        int32 PinIndex = 0;
        for (FDataflowInput* Input : Node->GetInputs())
        {
            if (!DataflowChaosWritePin(AssetPath, NodeGuid, TEXT("input"), PinIndex++, Input))
            {
                OutError = TEXT("failed writing canonical Dataflow input pin: ") + AssetPath;
                return false;
            }
        }
        PinIndex = 0;
        for (FDataflowOutput* Output : Node->GetOutputs())
        {
            if (!DataflowChaosWritePin(AssetPath, NodeGuid, TEXT("output"), PinIndex++, Output))
            {
                OutError = TEXT("failed writing canonical Dataflow output pin: ") + AssetPath;
                return false;
            }
        }
    }

    for (const UE::Dataflow::FLink& Link : GraphEdges)
    {
        TSharedRef<FJsonObject> EdgeRow = MakeShared<FJsonObject>();
        EdgeRow->SetStringField(TEXT("asset_path"), AssetPath);
        EdgeRow->SetStringField(TEXT("source_node_guid"), DataflowChaosGuidText(Link.OutputNode));
        EdgeRow->SetStringField(TEXT("source_pin_guid"), DataflowChaosGuidText(Link.Output));
        EdgeRow->SetStringField(TEXT("target_node_guid"), DataflowChaosGuidText(Link.InputNode));
        EdgeRow->SetStringField(TEXT("target_pin_guid"), DataflowChaosGuidText(Link.Input));
        if (!GDataflowChaosWriters.Edges.Write(EdgeRow))
        {
            OutError = TEXT("failed writing canonical Dataflow edge row: ") + AssetPath;
            return false;
        }
        ++GDataflowChaosCounts.Edges;
    }

    TSharedRef<FJsonObject> GraphRow = MakeShared<FJsonObject>();
    GraphRow->SetStringField(TEXT("asset_path"), AssetPath);
    GraphRow->SetStringField(TEXT("asset_class"), DataflowAsset->GetClass()->GetPathName());
    GraphRow->SetNumberField(TEXT("node_count"), GraphNodes.Num());
    GraphRow->SetNumberField(TEXT("edge_count"), GraphEdges.Num());
    GraphRow->SetNumberField(TEXT("asset_property_count"), GDataflowChaosCounts.DataflowAssetProperties - AssetPropertyStart);
    GraphRow->SetNumberField(TEXT("asset_reference_count"), GDataflowChaosCounts.DataflowAssetReferences - AssetReferenceStart);
    if (!GDataflowChaosWriters.Graphs.Write(GraphRow))
    {
        OutError = TEXT("failed writing canonical Dataflow graph row: ") + AssetPath;
        return false;
    }
    ++GDataflowChaosCounts.Graphs;
    return true;
}

static bool DataflowChaosWriteGeometryCollection(UObject* AssetObject, FString& OutError)
{
    if (!AssetObject) return true;
    const FString AssetPath = AssetObject->GetPathName();
    ++GDataflowChaosCounts.GeometryCollections;
    const int64 PropertyStart = GDataflowChaosCounts.GeometryCollectionProperties;
    const int64 ReferenceStart = GDataflowChaosCounts.GeometryCollectionReferences;
    UObject* DefaultObject = AssetObject->GetClass()->GetDefaultObject(false);
    const TSet<FName>& Roots = DataflowChaosGeometryCollectionBehaviorRoots();
    if (!DataflowChaosWriteProperties(
            AssetObject->GetClass(),
            AssetObject,
            DefaultObject,
            AssetObject,
            DefaultObject,
            AssetPath,
            AssetPath,
            TEXT("geometry_collection"),
            AssetObject->GetClass()->GetPathName(),
            GDataflowChaosWriters.GeometryCollectionProperties,
            GDataflowChaosWriters.GeometryCollectionReferences,
            GDataflowChaosCounts.GeometryCollectionProperties,
            GDataflowChaosCounts.GeometryCollectionReferences,
            &Roots))
    {
        OutError = TEXT("failed reflecting canonical Geometry Collection behavior properties: ") + AssetPath;
        return false;
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("asset_class"), AssetObject->GetClass()->GetPathName());
    Row->SetStringField(TEXT("dataflow_asset"), DataflowChaosObjectPropertyPath(AssetObject, TEXT("DataflowAsset")));
    Row->SetStringField(TEXT("dataflow_terminal"), DataflowChaosNestedField(AssetObject, TEXT("DataflowInstance"), TEXT("DataflowTerminal")));
    Row->SetNumberField(TEXT("property_count"), GDataflowChaosCounts.GeometryCollectionProperties - PropertyStart);
    Row->SetNumberField(TEXT("reference_count"), GDataflowChaosCounts.GeometryCollectionReferences - ReferenceStart);
    Row->SetBoolField(TEXT("geometry_source_in_behavior_schema"), false);
    if (!GDataflowChaosWriters.GeometryCollections.Write(Row))
    {
        OutError = TEXT("failed writing canonical Geometry Collection row: ") + AssetPath;
        return false;
    }
    return true;
}

static FString DataflowChaosAssetKind(UObject* Object)
{
    if (!Object) return FString();
    const FString ClassPath = Object->GetClass()->GetPathName();
    if (ClassPath == TEXT("/Script/DataflowEngine.Dataflow")) return TEXT("dataflow");
    if (ClassPath == TEXT("/Script/GeometryCollectionEngine.GeometryCollection")) return TEXT("geometry_collection");
    return FString();
}

static bool DataflowChaosScanLoadedAsset(const FString& AssetPath, FString& OutError)
{
    UObject* Object = StaticLoadObject(UObject::StaticClass(), nullptr, *AssetPath);
    if (!Object) return true;
    ++GDataflowChaosCounts.LoadedAssets;
    const FString Kind = DataflowChaosAssetKind(Object);
    if (Kind == TEXT("dataflow")) return DataflowChaosWriteDataflow(Cast<UDataflow>(Object), OutError);
    if (Kind == TEXT("geometry_collection")) return DataflowChaosWriteGeometryCollection(Object, OutError);
    return true;
}
