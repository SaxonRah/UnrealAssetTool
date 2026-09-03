struct FUAFCounts
{
    int64 Candidates = 0;
    int64 ScopedCandidates = 0;
    int64 LoadedAssets = 0;
    int64 Assets = 0;
    int64 Entries = 0;
    int64 Variables = 0;
    int64 Components = 0;
    int64 EntryPoints = 0;
    int64 RigVMGraphs = 0;
    int64 RigVMNodes = 0;
    int64 RigVMPins = 0;
    int64 RigVMLinks = 0;
    int64 VariableUsages = 0;
    int64 TruncatedValues = 0;
};

struct FUAFWriters
{
    FJsonlWriter Assets;
    FJsonlWriter Entries;
    FJsonlWriter Variables;
    FJsonlWriter Components;
    FJsonlWriter EntryPoints;
    FJsonlWriter RigVMGraphs;
    FJsonlWriter RigVMNodes;
    FJsonlWriter RigVMPins;
    FJsonlWriter RigVMLinks;
    FJsonlWriter VariableUsages;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("uaf_assets.jsonl"))) &&
            Entries.Open(FPaths::Combine(OutputDir, TEXT("uaf_entries.jsonl"))) &&
            Variables.Open(FPaths::Combine(OutputDir, TEXT("uaf_variables.jsonl"))) &&
            Components.Open(FPaths::Combine(OutputDir, TEXT("uaf_components.jsonl"))) &&
            EntryPoints.Open(FPaths::Combine(OutputDir, TEXT("uaf_entry_points.jsonl"))) &&
            RigVMGraphs.Open(FPaths::Combine(OutputDir, TEXT("uaf_rigvm_graphs.jsonl"))) &&
            RigVMNodes.Open(FPaths::Combine(OutputDir, TEXT("uaf_rigvm_nodes.jsonl"))) &&
            RigVMPins.Open(FPaths::Combine(OutputDir, TEXT("uaf_rigvm_pins.jsonl"))) &&
            RigVMLinks.Open(FPaths::Combine(OutputDir, TEXT("uaf_rigvm_links.jsonl"))) &&
            VariableUsages.Open(FPaths::Combine(OutputDir, TEXT("uaf_variable_usages.jsonl")));
    }
};

static FUAFCounts GUAFCounts;
static FUAFWriters GUAFWriters;
static constexpr int32 UAFMaxExportChars = 65536;

static bool UAFIsExactAssetClass(const FString& ClassPath)
{
    return ClassPath == TEXT("/Script/UAF.UAFSystem") ||
        ClassPath == TEXT("/Script/UAFAnimGraph.UAFAnimGraph");
}

static FString UAFAssetKind(const FString& ClassPath)
{
    if (ClassPath == TEXT("/Script/UAF.UAFSystem")) return TEXT("system");
    if (ClassPath == TEXT("/Script/UAFAnimGraph.UAFAnimGraph")) return TEXT("animation_graph");
    return TEXT("");
}

static FString UAFExportPropertyValue(UObject* Object, const FName PropertyName, bool& bTruncated)
{
    bTruncated = false;
    if (!Object) return FString();
    const FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
    if (!Property) return FString();
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    if (!ValuePtr) return FString();
    FString Value;
    Property->ExportTextItem_Direct(Value, ValuePtr, nullptr, Object, PPF_None, nullptr);
    if (Value.Len() > UAFMaxExportChars)
    {
        Value.LeftInline(UAFMaxExportChars, EAllowShrinking::No);
        bTruncated = true;
        ++GUAFCounts.TruncatedValues;
    }
    return Value;
}

static FString UAFExportPropertyValue(UObject* Object, const FName PropertyName)
{
    bool bTruncated = false;
    return UAFExportPropertyValue(Object, PropertyName, bTruncated);
}

static FString UAFObjectPropertyPath(UObject* Object, const FName PropertyName)
{
    if (!Object) return FString();
    const FObjectPropertyBase* Property = CastField<FObjectPropertyBase>(
        Object->GetClass()->FindPropertyByName(PropertyName));
    if (!Property) return FString();
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    UObject* Value = ValuePtr ? Property->GetObjectPropertyValue(ValuePtr) : nullptr;
    return Value ? Value->GetPathName() : FString();
}

static FString UAFNestedExport(UObject* Object, const FName RootProperty, const FName NestedProperty)
{
    if (!Object) return FString();
    const FStructProperty* Root = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(RootProperty));
    if (!Root || !Root->Struct) return FString();
    const void* RootPtr = Root->ContainerPtrToValuePtr<void>(Object);
    if (!RootPtr) return FString();
    const FProperty* Nested = Root->Struct->FindPropertyByName(NestedProperty);
    if (!Nested) return FString();
    const void* ValuePtr = Nested->ContainerPtrToValuePtr<void>(RootPtr);
    FString Value;
    Nested->ExportTextItem_Direct(Value, ValuePtr, nullptr, Object, PPF_None, nullptr);
    if (Value.Len() > UAFMaxExportChars)
    {
        Value.LeftInline(UAFMaxExportChars, EAllowShrinking::No);
        ++GUAFCounts.TruncatedValues;
    }
    return Value;
}

static FString UAFNestedObjectPath(UObject* Object, const FName RootProperty, const FName NestedProperty)
{
    if (!Object) return FString();
    const FStructProperty* Root = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(RootProperty));
    if (!Root || !Root->Struct) return FString();
    const void* RootPtr = Root->ContainerPtrToValuePtr<void>(Object);
    if (!RootPtr) return FString();
    const FObjectPropertyBase* Nested = CastField<FObjectPropertyBase>(Root->Struct->FindPropertyByName(NestedProperty));
    if (!Nested) return FString();
    const void* ValuePtr = Nested->ContainerPtrToValuePtr<void>(RootPtr);
    UObject* Value = ValuePtr ? Nested->GetObjectPropertyValue(ValuePtr) : nullptr;
    return Value ? Value->GetPathName() : FString();
}

static FString UAFPinDirectionName(const ERigVMPinDirection Direction)
{
    if (const UEnum* Enum = StaticEnum<ERigVMPinDirection>())
        return Enum->GetNameStringByValue(static_cast<int64>(Direction));
    return FString::FromInt(static_cast<int32>(Direction));
}

static bool UAFWriteEntry(UObject* Object, const FString& AssetPath)
{
    if (!Object) return true;
    const FString ClassPath = Object->GetClass()->GetPathName();
    FString Kind;
    if (ClassPath == TEXT("/Script/UAFAnimGraphUncookedOnly.AnimNextAnimationGraphEntry"))
        Kind = TEXT("animation_graph");
    else if (ClassPath == TEXT("/Script/UAFUncookedOnly.AnimNextEventGraphEntry"))
        Kind = TEXT("event_graph");
    else
        return true;

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("entry_path"), Object->GetPathName());
    Row->SetStringField(TEXT("entry_class"), ClassPath);
    Row->SetStringField(TEXT("entry_kind"), Kind);
    Row->SetStringField(TEXT("graph_name"), UAFExportPropertyValue(Object, TEXT("GraphName")));
    Row->SetStringField(TEXT("access"), UAFExportPropertyValue(Object, TEXT("Access")));
    Row->SetStringField(TEXT("graph_path"), UAFObjectPropertyPath(Object, TEXT("Graph")));
    Row->SetStringField(TEXT("ed_graph_path"), UAFObjectPropertyPath(Object, TEXT("EdGraph")));
    Row->SetStringField(TEXT("hidden_in_outliner"), UAFExportPropertyValue(Object, TEXT("bHiddenInOutliner")));
    if (!GUAFWriters.Entries.Write(Row)) return false;
    ++GUAFCounts.Entries;
    return true;
}

static bool UAFWriteVariable(UObject* Object, const FString& AssetPath, TMap<FString, TPair<FString, FString>>& VariablesByName)
{
    if (!Object || Object->GetClass()->GetPathName() != TEXT("/Script/UAFUncookedOnly.AnimNextVariableEntry"))
        return true;

    const FString Name = UAFExportPropertyValue(Object, TEXT("ParameterName"));
    const FString Guid = UAFExportPropertyValue(Object, TEXT("Guid"));
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("variable_path"), Object->GetPathName());
    Row->SetStringField(TEXT("variable_guid"), Guid);
    Row->SetStringField(TEXT("variable_name"), Name);
    Row->SetStringField(TEXT("access"), UAFExportPropertyValue(Object, TEXT("Access")));
    Row->SetStringField(TEXT("type_value"), UAFNestedExport(Object, TEXT("Type"), TEXT("ValueType")));
    Row->SetStringField(TEXT("type_container"), UAFNestedExport(Object, TEXT("Type"), TEXT("ContainerType")));
    Row->SetStringField(TEXT("type_object"), UAFNestedObjectPath(Object, TEXT("Type"), TEXT("ValueTypeObject")));
    Row->SetStringField(TEXT("default_value"), UAFExportPropertyValue(Object, TEXT("DefaultValue")));
    Row->SetStringField(TEXT("binding"), UAFExportPropertyValue(Object, TEXT("Binding")));
    if (!GUAFWriters.Variables.Write(Row)) return false;
    ++GUAFCounts.Variables;
    if (!Name.IsEmpty()) VariablesByName.Add(Name, TPair<FString, FString>(Guid, Object->GetPathName()));
    return true;
}

static bool UAFWriteComponents(UObject* Asset, const FString& AssetPath)
{
    if (!Asset) return true;
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Asset->GetClass()->FindPropertyByName(TEXT("Components")));
    if (!ArrayProperty) return true;
    const void* ValuePtr = ArrayProperty->ContainerPtrToValuePtr<void>(Asset);
    if (!ValuePtr) return true;
    FScriptArrayHelper Helper(ArrayProperty, const_cast<void*>(ValuePtr));
    const FStructProperty* Inner = CastField<FStructProperty>(ArrayProperty->Inner);
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Element = Helper.GetRawPtr(Index);
        FString Value;
        bool bTruncated = false;
        ArrayProperty->Inner->ExportTextItem_Direct(Value, Element, nullptr, Asset, PPF_None, nullptr);
        if (Value.Len() > UAFMaxExportChars)
        {
            Value.LeftInline(UAFMaxExportChars, EAllowShrinking::No);
            bTruncated = true;
            ++GUAFCounts.TruncatedValues;
        }
        FString ComponentType;
        if (Inner && Inner->Struct)
        {
            if (const FObjectPropertyBase* TypeProperty = CastField<FObjectPropertyBase>(Inner->Struct->FindPropertyByName(TEXT("ComponentType"))))
            {
                const void* TypePtr = TypeProperty->ContainerPtrToValuePtr<void>(Element);
                UObject* TypeObject = TypePtr ? TypeProperty->GetObjectPropertyValue(TypePtr) : nullptr;
                if (TypeObject) ComponentType = TypeObject->GetPathName();
            }
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetNumberField(TEXT("component_index"), Index);
        Row->SetStringField(TEXT("component_struct"), Inner && Inner->Struct ? Inner->Struct->GetPathName() : ArrayProperty->Inner->GetCPPType());
        Row->SetStringField(TEXT("component_type"), ComponentType);
        Row->SetStringField(TEXT("value"), Value);
        Row->SetBoolField(TEXT("truncated"), bTruncated);
        if (!GUAFWriters.Components.Write(Row)) return false;
        ++GUAFCounts.Components;
    }
    return true;
}

static bool UAFWriteEntryPoints(UObject* Asset, const FString& AssetPath)
{
    if (!Asset || Asset->GetClass()->GetPathName() != TEXT("/Script/UAFAnimGraph.UAFAnimGraph")) return true;
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Asset->GetClass()->FindPropertyByName(TEXT("EntryPoints")));
    const FStructProperty* Inner = ArrayProperty ? CastField<FStructProperty>(ArrayProperty->Inner) : nullptr;
    if (!ArrayProperty || !Inner || !Inner->Struct) return true;
    const void* ValuePtr = ArrayProperty->ContainerPtrToValuePtr<void>(Asset);
    if (!ValuePtr) return true;
    FScriptArrayHelper Helper(ArrayProperty, const_cast<void*>(ValuePtr));
    const FProperty* NameProperty = Inner->Struct->FindPropertyByName(TEXT("EntryPointName"));
    const FStructProperty* TraitHandleProperty = CastField<FStructProperty>(Inner->Struct->FindPropertyByName(TEXT("RootTraitHandle")));
    const FProperty* PackedProperty = TraitHandleProperty && TraitHandleProperty->Struct
        ? TraitHandleProperty->Struct->FindPropertyByName(TEXT("PackedTraitIndexAndNodeHandle")) : nullptr;
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Element = Helper.GetRawPtr(Index);
        FString Name;
        if (NameProperty)
            NameProperty->ExportTextItem_Direct(Name, NameProperty->ContainerPtrToValuePtr<void>(Element), nullptr, Asset, PPF_None, nullptr);
        FString Packed;
        if (TraitHandleProperty && PackedProperty)
        {
            const void* Trait = TraitHandleProperty->ContainerPtrToValuePtr<void>(Element);
            PackedProperty->ExportTextItem_Direct(Packed, PackedProperty->ContainerPtrToValuePtr<void>(Trait), nullptr, Asset, PPF_None, nullptr);
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetNumberField(TEXT("entry_point_index"), Index);
        Row->SetStringField(TEXT("entry_point_name"), Name);
        Row->SetStringField(TEXT("packed_root_trait_handle"), Packed);
        if (!GUAFWriters.EntryPoints.Write(Row)) return false;
        ++GUAFCounts.EntryPoints;
    }
    return true;
}

static bool UAFWriteRigVMPin(const FString& AssetPath, const FString& GraphPath, const FString& NodePath, URigVMPin* Pin, const int32 Depth)
{
    if (!Pin) return true;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("graph_path"), GraphPath);
    Row->SetStringField(TEXT("node_path"), NodePath);
    Row->SetStringField(TEXT("pin_path"), Pin->GetPinPath(true));
    Row->SetStringField(TEXT("pin_name"), Pin->GetName());
    Row->SetStringField(TEXT("direction"), UAFPinDirectionName(Pin->GetDirection()));
    Row->SetNumberField(TEXT("depth"), Depth);
    Row->SetNumberField(TEXT("pin_index"), Pin->GetPinIndex());
    Row->SetStringField(TEXT("cpp_type"), Pin->GetCPPType());
    Row->SetStringField(TEXT("cpp_type_object"), Pin->GetCPPTypeObject() ? Pin->GetCPPTypeObject()->GetPathName() : FString());
    Row->SetStringField(TEXT("default_value"), Pin->GetDefaultValue());
    Row->SetStringField(TEXT("original_default_value"), Pin->GetOriginalDefaultValue());
    Row->SetBoolField(TEXT("hidden"), Pin->GetDirection() == ERigVMPinDirection::Hidden);
    Row->SetNumberField(TEXT("subpin_count"), Pin->GetSubPins().Num());
    if (!GUAFWriters.RigVMPins.Write(Row)) return false;
    ++GUAFCounts.RigVMPins;
    for (URigVMPin* Child : Pin->GetSubPins())
        if (!UAFWriteRigVMPin(AssetPath, GraphPath, NodePath, Child, Depth + 1)) return false;
    return true;
}

static bool UAFWriteRigVMGraph(
    const FString& AssetPath,
    URigVMGraph* Graph,
    const TMap<FString, TPair<FString, FString>>& VariablesByName)
{
    if (!Graph) return true;
    const FString GraphPath = Graph->GetPathName();
    const TArray<URigVMNode*>& Nodes = Graph->GetNodes();
    const TArray<URigVMLink*>& Links = Graph->GetLinks();
    const TSubclassOf<URigVMSchema> SchemaClass = Graph->GetSchemaClass();

    TSharedRef<FJsonObject> GraphRow = MakeShared<FJsonObject>();
    GraphRow->SetStringField(TEXT("asset_path"), AssetPath);
    GraphRow->SetStringField(TEXT("graph_path"), GraphPath);
    GraphRow->SetStringField(TEXT("graph_name"), Graph->GetGraphName());
    GraphRow->SetStringField(TEXT("graph_class"), Graph->GetClass()->GetPathName());
    GraphRow->SetStringField(TEXT("schema_class"), SchemaClass ? SchemaClass.Get()->GetPathName() : FString());
    GraphRow->SetStringField(TEXT("execute_context_struct"), Graph->GetExecuteContextStruct() ? Graph->GetExecuteContextStruct()->GetPathName() : FString());
    GraphRow->SetNumberField(TEXT("node_count"), Nodes.Num());
    GraphRow->SetNumberField(TEXT("link_count"), Links.Num());
    if (!GUAFWriters.RigVMGraphs.Write(GraphRow)) return false;
    ++GUAFCounts.RigVMGraphs;

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
        FString Operation = TEXT("rigvm_node");
        FString UnitStruct;
        if (URigVMUnitNode* UnitNode = Cast<URigVMUnitNode>(Node))
        {
            Operation = TEXT("rigvm_unit");
            UnitStruct = UnitNode->GetScriptStruct() ? UnitNode->GetScriptStruct()->GetPathName() : FString();
            NodeRow->SetStringField(TEXT("method_name"), UnitNode->GetMethodName().ToString());
            NodeRow->SetStringField(TEXT("event_name"), UnitNode->GetEventName().ToString());
        }
        else if (Node->GetClass()->GetPathName() == TEXT("/Script/RigVMDeveloper.RigVMVariableNode"))
            Operation = TEXT("rigvm_variable");
        else if (Node->GetClass()->GetPathName() == TEXT("/Script/RigVMDeveloper.RigVMDispatchNode"))
            Operation = TEXT("rigvm_dispatch");
        NodeRow->SetStringField(TEXT("operation"), Operation);
        NodeRow->SetStringField(TEXT("unit_script_struct"), UnitStruct);
        if (!GUAFWriters.RigVMNodes.Write(NodeRow)) return false;
        ++GUAFCounts.RigVMNodes;

        FString VariableName;
        for (URigVMPin* Pin : Node->GetPins())
        {
            if (Pin && Pin->GetName() == TEXT("Variable")) VariableName = Pin->GetDefaultValue();
            if (!UAFWriteRigVMPin(AssetPath, GraphPath, NodePath, Pin, 0)) return false;
        }
        if (Operation == TEXT("rigvm_variable") && !VariableName.IsEmpty())
        {
            const TPair<FString, FString>* Variable = VariablesByName.Find(VariableName);
            if (Variable)
            {
                TSharedRef<FJsonObject> Usage = MakeShared<FJsonObject>();
                Usage->SetStringField(TEXT("asset_path"), AssetPath);
                Usage->SetStringField(TEXT("graph_path"), GraphPath);
                Usage->SetStringField(TEXT("node_path"), NodePath);
                Usage->SetStringField(TEXT("variable_name"), VariableName);
                Usage->SetStringField(TEXT("variable_guid"), Variable->Key);
                Usage->SetStringField(TEXT("variable_path"), Variable->Value);
                if (!GUAFWriters.VariableUsages.Write(Usage)) return false;
                ++GUAFCounts.VariableUsages;
            }
        }
    }

    for (URigVMLink* Link : Links)
    {
        if (!Link) continue;
        URigVMPin* SourcePin = Link->GetSourcePin();
        URigVMPin* TargetPin = Link->GetTargetPin();
        if (!SourcePin || !TargetPin) continue;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetStringField(TEXT("graph_path"), GraphPath);
        Row->SetStringField(TEXT("link_path"), Link->GetPathName());
        Row->SetStringField(TEXT("source_node_path"), SourcePin->GetNode() ? SourcePin->GetNode()->GetNodePath(true) : FString());
        Row->SetStringField(TEXT("source_pin_path"), SourcePin->GetPinPath(true));
        Row->SetStringField(TEXT("target_node_path"), TargetPin->GetNode() ? TargetPin->GetNode()->GetNodePath(true) : FString());
        Row->SetStringField(TEXT("target_pin_path"), TargetPin->GetPinPath(true));
        if (!GUAFWriters.RigVMLinks.Write(Row)) return false;
        ++GUAFCounts.RigVMLinks;
    }
    return true;
}

static bool UAFScanLoadedAsset(const FString& ObjectPath, FString& OutError)
{
    UObject* Asset = StaticLoadObject(UObject::StaticClass(), nullptr, *ObjectPath);
    if (!Asset)
    {
        OutError = TEXT("failed loading exact UAF asset: ") + ObjectPath;
        return false;
    }
    const FString ClassPath = Asset->GetClass()->GetPathName();
    if (!UAFIsExactAssetClass(ClassPath)) return true;
    ++GUAFCounts.LoadedAssets;
    ++GUAFCounts.Assets;

    TArray<UObject*> Objects;
    GetObjectsWithOuter(Asset, Objects, EGetObjectsFlags::IncludeNestedObjects);
    Objects.Sort([](const UObject& A, const UObject& B) { return A.GetPathName() < B.GetPathName(); });

    TMap<FString, TPair<FString, FString>> VariablesByName;
    int64 EntryStart = GUAFCounts.Entries;
    int64 VariableStart = GUAFCounts.Variables;
    int64 GraphStart = GUAFCounts.RigVMGraphs;
    int64 ComponentStart = GUAFCounts.Components;
    int64 EntryPointStart = GUAFCounts.EntryPoints;

    for (UObject* Object : Objects)
    {
        if (!UAFWriteEntry(Object, ObjectPath) || !UAFWriteVariable(Object, ObjectPath, VariablesByName))
        {
            OutError = TEXT("failed writing UAF entry/variable rows: ") + ObjectPath;
            return false;
        }
    }
    if (!UAFWriteComponents(Asset, ObjectPath) || !UAFWriteEntryPoints(Asset, ObjectPath))
    {
        OutError = TEXT("failed writing UAF component/entry-point rows: ") + ObjectPath;
        return false;
    }

    TSet<FString> SeenGraphs;
    for (UObject* Object : Objects)
    {
        URigVMGraph* Graph = Cast<URigVMGraph>(Object);
        if (!Graph || SeenGraphs.Contains(Graph->GetPathName())) continue;
        SeenGraphs.Add(Graph->GetPathName());
        if (!UAFWriteRigVMGraph(ObjectPath, Graph, VariablesByName))
        {
            OutError = TEXT("failed writing UAF RigVM graph: ") + Graph->GetPathName();
            return false;
        }
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), ObjectPath);
    Row->SetStringField(TEXT("asset_class"), ClassPath);
    Row->SetStringField(TEXT("asset_kind"), UAFAssetKind(ClassPath));
    Row->SetStringField(TEXT("rigvm_path"), UAFObjectPropertyPath(Asset, TEXT("RigVM")));
    Row->SetStringField(TEXT("editor_data_path"), UAFObjectPropertyPath(Asset, TEXT("EditorData")));
    Row->SetStringField(TEXT("required_plugins"), UAFExportPropertyValue(Asset, TEXT("RequiredPlugins")));
    Row->SetStringField(TEXT("default_entry_point"), UAFExportPropertyValue(Asset, TEXT("DefaultEntryPoint")));
    Row->SetNumberField(TEXT("entry_count"), GUAFCounts.Entries - EntryStart);
    Row->SetNumberField(TEXT("variable_count"), GUAFCounts.Variables - VariableStart);
    Row->SetNumberField(TEXT("component_count"), GUAFCounts.Components - ComponentStart);
    Row->SetNumberField(TEXT("entry_point_count"), GUAFCounts.EntryPoints - EntryPointStart);
    Row->SetNumberField(TEXT("rigvm_graph_count"), GUAFCounts.RigVMGraphs - GraphStart);
    if (!GUAFWriters.Assets.Write(Row))
    {
        OutError = TEXT("failed writing UAF asset row: ") + ObjectPath;
        return false;
    }
    return true;
}
