static bool IsMetaSoundNodeStruct(const UScriptStruct* Struct)
{
    if (!Struct)
    {
        return false;
    }
    const FString Name = Struct->GetName();
    return Name == TEXT("MetasoundFrontendNode") || Name == TEXT("MetaSoundFrontendNode") ||
        Name.EndsWith(TEXT("MetasoundFrontendNode")) || Name.EndsWith(TEXT("MetaSoundFrontendNode"));
}

static bool IsMetaSoundEdgeStruct(const UScriptStruct* Struct)
{
    if (!Struct)
    {
        return false;
    }
    const FString Name = Struct->GetName();
    return Name == TEXT("MetasoundFrontendEdge") || Name == TEXT("MetaSoundFrontendEdge") ||
        Name.EndsWith(TEXT("MetasoundFrontendEdge")) || Name.EndsWith(TEXT("MetaSoundFrontendEdge"));
}

static bool ScanMetaSoundStructsRecursive(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& AssetPath,
    const FString& PropertyPath,
    UObject* Owner,
    int32 Depth,
    int32& NodeIndex,
    int32& EdgeIndex,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Property || !ValuePtr || Depth > MaxReferenceDepth ||
        NodeIndex + EdgeIndex >= MaxStructuredRowsPerAsset)
    {
        return true;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        UScriptStruct* Struct = StructProperty->Struct;
        if (!Struct)
        {
            return true;
        }

        if (IsMetaSoundNodeStruct(Struct))
        {
            bool bTruncated = false;
            const FString Raw = ExportProperty(Property, ValuePtr, Owner, bTruncated);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("asset_path"), AssetPath);
            Row->SetNumberField(TEXT("node_index"), NodeIndex++);
            Row->SetStringField(TEXT("property_path"), PropertyPath);
            Row->SetStringField(TEXT("struct_type"), Struct->GetPathName());
            Row->SetStringField(TEXT("node_id"), ExportFirstField(Struct, ValuePtr, Owner, {TEXT("ID"), TEXT("NodeID"), TEXT("Guid")}));
            Row->SetStringField(TEXT("class_id"), ExportFirstField(Struct, ValuePtr, Owner, {TEXT("ClassID"), TEXT("ClassId")}));
            Row->SetStringField(TEXT("name"), ExportFirstField(Struct, ValuePtr, Owner, {TEXT("Name"), TEXT("DisplayName")}));
            Row->SetStringField(TEXT("interface"), ExportFirstField(Struct, ValuePtr, Owner, {TEXT("Interface"), TEXT("NodeInterface")}));
            Row->SetStringField(TEXT("style"), ExportFirstField(Struct, ValuePtr, Owner, {TEXT("Style")}));
            Row->SetStringField(TEXT("raw_value"), Raw);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.MetaSoundNodes.Write(Row))
            {
                return false;
            }
            ++Counts.MetaSoundNodes;
            return true;
        }

        if (IsMetaSoundEdgeStruct(Struct))
        {
            bool bTruncated = false;
            const FString Raw = ExportProperty(Property, ValuePtr, Owner, bTruncated);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("asset_path"), AssetPath);
            Row->SetNumberField(TEXT("edge_index"), EdgeIndex++);
            Row->SetStringField(TEXT("property_path"), PropertyPath);
            Row->SetStringField(TEXT("struct_type"), Struct->GetPathName());
            Row->SetStringField(TEXT("from_node_id"), ExportFirstField(Struct, ValuePtr, Owner, {TEXT("FromNodeID"), TEXT("FromNodeId")}));
            Row->SetStringField(TEXT("from_vertex_id"), ExportFirstField(Struct, ValuePtr, Owner, {TEXT("FromVertexID"), TEXT("FromVertexId")}));
            Row->SetStringField(TEXT("to_node_id"), ExportFirstField(Struct, ValuePtr, Owner, {TEXT("ToNodeID"), TEXT("ToNodeId")}));
            Row->SetStringField(TEXT("to_vertex_id"), ExportFirstField(Struct, ValuePtr, Owner, {TEXT("ToVertexID"), TEXT("ToVertexId")}));
            Row->SetStringField(TEXT("raw_value"), Raw);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.MetaSoundEdges.Write(Row))
            {
                return false;
            }
            ++Counts.MetaSoundEdges;
            return true;
        }

        for (TFieldIterator<FProperty> It(Struct); It; ++It)
        {
            const FProperty* Inner = *It;
            if (!ShouldInspectProperty(Inner))
            {
                continue;
            }
            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const FString Child = PropertyPath + TEXT(".") + Inner->GetName() +
                    (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                if (!ScanMetaSoundStructsRecursive(
                    Inner, InnerValue, AssetPath, Child, Owner, Depth + 1,
                    NodeIndex, EdgeIndex, Writers, Counts))
                {
                    return false;
                }
            }
        }
        return true;
    }

    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
        const int32 Limit = FMath::Min(Helper.Num(), 16384);
        for (int32 Index = 0; Index < Limit; ++Index)
        {
            if (!ScanMetaSoundStructsRecursive(
                ArrayProperty->Inner,
                Helper.GetRawPtr(Index),
                AssetPath,
                FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                Owner,
                Depth + 1,
                NodeIndex,
                EdgeIndex,
                Writers,
                Counts))
            {
                return false;
            }
        }
        return true;
    }

    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, ValuePtr);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < 4096; ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            if (!ScanMetaSoundStructsRecursive(
                SetProperty->ElementProp,
                Helper.GetElementPtr(Index),
                AssetPath,
                FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++),
                Owner,
                Depth + 1,
                NodeIndex,
                EdgeIndex,
                Writers,
                Counts))
            {
                return false;
            }
        }
        return true;
    }

    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, ValuePtr);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < 4096; ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            const FString Base = FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++);
            if (!ScanMetaSoundStructsRecursive(MapProperty->KeyProp, Helper.GetKeyPtr(Index), AssetPath,
                Base + TEXT(".key"), Owner, Depth + 1, NodeIndex, EdgeIndex, Writers, Counts)) return false;
            if (!ScanMetaSoundStructsRecursive(MapProperty->ValueProp, Helper.GetValuePtr(Index), AssetPath,
                Base + TEXT(".value"), Owner, Depth + 1, NodeIndex, EdgeIndex, Writers, Counts)) return false;
        }
    }
    return true;
}

static bool ScanMetaSoundDocument(
    UObject* Object,
    const FString& AssetPath,
    int32& OutNodeCount,
    int32& OutEdgeCount,
    FWriters& Writers,
    FCounts& Counts)
{
    OutNodeCount = 0;
    OutEdgeCount = 0;
    if (!Object)
    {
        return true;
    }
    TSet<FString> SeenRoots;
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
            if (SeenRoots.Contains(Key))
            {
                continue;
            }
            SeenRoots.Add(Key);
            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
            {
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
                const FString Path = Property->GetName() +
                    (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                if (!ScanMetaSoundStructsRecursive(
                    Property, ValuePtr, AssetPath, Path, Object, 0,
                    OutNodeCount, OutEdgeCount, Writers, Counts))
                {
                    return false;
                }
            }
        }
    }
    return true;
}

static bool ScanSoundCueNodes(
    UObject* Cue,
    const FString& AssetPath,
    int32& OutNodeCount,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    OutNodeCount = 0;
    if (!Cue)
    {
        return true;
    }
    const FArrayProperty* NodesProperty = CastField<FArrayProperty>(Cue->GetClass()->FindPropertyByName(TEXT("AllNodes")));
    if (!NodesProperty)
    {
        return true;
    }
    const FObjectPropertyBase* InnerObject = CastField<FObjectPropertyBase>(NodesProperty->Inner);
    if (!InnerObject)
    {
        return true;
    }
    const void* ValuePtr = NodesProperty->ContainerPtrToValuePtr<void>(Cue);
    if (!ValuePtr)
    {
        return true;
    }
    FScriptArrayHelper Helper(NodesProperty, ValuePtr);
    const int32 Limit = FMath::Min(Helper.Num(), MaxStructuredRowsPerAsset);
    for (int32 Index = 0; Index < Limit; ++Index)
    {
        UObject* Node = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
        if (!Node)
        {
            continue;
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("sound_cue_path"), AssetPath);
        Row->SetNumberField(TEXT("node_index"), OutNodeCount++);
        Row->SetStringField(TEXT("node_path"), Node->GetPathName());
        Row->SetStringField(TEXT("node_class"), Node->GetClass()->GetPathName());
        Row->SetStringField(TEXT("node_name"), Node->GetName());
        Row->SetNumberField(TEXT("child_count"), GetArrayCount(Node, TEXT("ChildNodes")));
        if (!Writers.SoundCueNodes.Write(Row))
        {
            return false;
        }
        ++Counts.SoundCueNodes;
        if (!WriteObjectState(Node, AssetPath, TEXT("sound_cue_node"), Writers, Counts, SeenStateOwners))
        {
            return false;
        }
    }
    return true;
}

static bool ScanAudioAsset(
    UObject* Object,
    const FAssetData& Asset,
    const FString& Kind,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Object)
    {
        return true;
    }
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    int32 SoundCueNodeCount = 0;
    int32 MetaSoundNodeCount = 0;
    int32 MetaSoundEdgeCount = 0;

    if (Kind == TEXT("sound_cue"))
    {
        if (!ScanSoundCueNodes(Object, AssetPath, SoundCueNodeCount, Writers, Counts, SeenStateOwners))
        {
            return false;
        }
    }
    if (Kind == TEXT("metasound_source") || Kind == TEXT("metasound_patch"))
    {
        if (!ScanMetaSoundDocument(Object, AssetPath, MetaSoundNodeCount, MetaSoundEdgeCount, Writers, Counts))
        {
            return false;
        }
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("audio_path"), AssetPath);
    Row->SetStringField(TEXT("audio_kind"), Kind);
    Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("duration"), ExportField(Object, TEXT("Duration")));
    Row->SetStringField(TEXT("volume_multiplier"), ExportFirstField(Object, {TEXT("VolumeMultiplier"), TEXT("Volume")}));
    Row->SetStringField(TEXT("pitch_multiplier"), ExportFirstField(Object, {TEXT("PitchMultiplier"), TEXT("Pitch")}));
    Row->SetStringField(TEXT("num_channels"), ExportFirstField(Object, {TEXT("NumChannels"), TEXT("Channels")}));
    Row->SetStringField(TEXT("sample_rate"), ExportFirstField(Object, {TEXT("SampleRate"), TEXT("ImportedSampleRate")}));
    UObject* Attenuation = GetFirstObjectField(Object, {TEXT("AttenuationSettings"), TEXT("Attenuation")});
    Row->SetStringField(TEXT("attenuation_path"), Attenuation ? Attenuation->GetPathName() : FString());
    Row->SetNumberField(TEXT("sound_cue_node_count"), SoundCueNodeCount);
    Row->SetNumberField(TEXT("metasound_node_count"), MetaSoundNodeCount);
    Row->SetNumberField(TEXT("metasound_edge_count"), MetaSoundEdgeCount);
    if (!Writers.AudioAssets.Write(Row))
    {
        return false;
    }
    ++Counts.AudioAssets;
    return true;
}
