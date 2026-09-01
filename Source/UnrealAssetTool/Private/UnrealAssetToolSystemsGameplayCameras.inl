struct FGameplayCameraCounts
{
    int64 Assets = 0;
    int64 Rigs = 0;
    int64 Nodes = 0;
    int64 NodeEdges = 0;
    int64 Transitions = 0;
    int64 Directors = 0;
    int64 RigReferences = 0;
};

struct FGameplayCameraWriters
{
    FJsonlWriter Assets;
    FJsonlWriter Rigs;
    FJsonlWriter Nodes;
    FJsonlWriter NodeEdges;
    FJsonlWriter Transitions;
    FJsonlWriter Directors;
    FJsonlWriter RigReferences;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("gameplay_camera_assets.jsonl"))) &&
            Rigs.Open(FPaths::Combine(OutputDir, TEXT("gameplay_camera_rigs.jsonl"))) &&
            Nodes.Open(FPaths::Combine(OutputDir, TEXT("gameplay_camera_nodes.jsonl"))) &&
            NodeEdges.Open(FPaths::Combine(OutputDir, TEXT("gameplay_camera_node_edges.jsonl"))) &&
            Transitions.Open(FPaths::Combine(OutputDir, TEXT("gameplay_camera_transitions.jsonl"))) &&
            Directors.Open(FPaths::Combine(OutputDir, TEXT("gameplay_camera_directors.jsonl"))) &&
            RigReferences.Open(FPaths::Combine(OutputDir, TEXT("gameplay_camera_rig_references.jsonl")));
    }
};

static FGameplayCameraCounts GGameplayCameraCounts;
static FGameplayCameraWriters GGameplayCameraWriters;

static bool IsGameplayCameraAssetClassPath(const FString& ClassPath)
{
    return ClassPath == TEXT("/Script/GameplayCameras.CameraAsset") ||
        ClassPath == TEXT("/Script/GameplayCameras.CameraRigAsset");
}

static bool IsGameplayCameraNodeClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("CameraNode"));
}

static bool IsGameplayCameraRigClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("CameraRigAsset"));
}

static bool IsGameplayCameraTransitionClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("CameraRigTransition"));
}

static bool IsGameplayCameraDirectorClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("CameraDirector"));
}

static void GatherGameplayCameraObjectArray(UObject* Owner, const FName PropertyName, TArray<UObject*>& Out)
{
    Out.Reset();
    if (!Owner)
    {
        return;
    }
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Owner->GetClass()->FindPropertyByName(PropertyName));
    if (!ArrayProperty)
    {
        return;
    }
    const FObjectPropertyBase* InnerObject = CastField<FObjectPropertyBase>(ArrayProperty->Inner);
    if (!InnerObject)
    {
        return;
    }
    const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(Owner);
    if (!ArrayValue)
    {
        return;
    }
    FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
    Out.Reserve(Helper.Num());
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        Out.Add(InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index)));
    }
}

struct FGameplayCameraObjectReference
{
    FString PropertyPath;
    UObject* Target = nullptr;
};

static void CollectGameplayCameraObjectReferences(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& PropertyPath,
    int32 Depth,
    TArray<FGameplayCameraObjectReference>& Out)
{
    if (!Property || !ValuePtr || Depth > MaxReferenceDepth || Out.Num() >= MaxReferencesPerRoot)
    {
        return;
    }

    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr);
        if (Target && (IsGameplayCameraNodeClass(Target->GetClass()) || IsGameplayCameraRigClass(Target->GetClass())))
        {
            FGameplayCameraObjectReference& Item = Out.AddDefaulted_GetRef();
            Item.PropertyPath = PropertyPath;
            Item.Target = Target;
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
                const FString Child = PropertyPath + TEXT(".") + Inner->GetName() +
                    (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                CollectGameplayCameraObjectReferences(Inner, InnerValue, Child, Depth + 1, Out);
            }
        }
        return;
    }

    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
        const int32 Limit = FMath::Min(Helper.Num(), 4096);
        for (int32 Index = 0; Index < Limit && Out.Num() < MaxReferencesPerRoot; ++Index)
        {
            CollectGameplayCameraObjectReferences(
                ArrayProperty->Inner,
                Helper.GetRawPtr(Index),
                FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                Depth + 1,
                Out);
        }
        return;
    }

    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, ValuePtr);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < 4096 && Out.Num() < MaxReferencesPerRoot; ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            CollectGameplayCameraObjectReferences(
                SetProperty->ElementProp,
                Helper.GetElementPtr(Index),
                FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++),
                Depth + 1,
                Out);
        }
        return;
    }

    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, ValuePtr);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < 4096 && Out.Num() < MaxReferencesPerRoot; ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            const FString Base = FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++);
            CollectGameplayCameraObjectReferences(MapProperty->KeyProp, Helper.GetKeyPtr(Index), Base + TEXT(".key"), Depth + 1, Out);
            CollectGameplayCameraObjectReferences(MapProperty->ValueProp, Helper.GetValuePtr(Index), Base + TEXT(".value"), Depth + 1, Out);
        }
    }
}

static void GatherGameplayCameraReferences(UObject* Owner, TArray<FGameplayCameraObjectReference>& Out)
{
    Out.Reset();
    if (!Owner)
    {
        return;
    }
    TSet<FString> SeenRoots;
    for (UClass* Class = Owner->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property))
            {
                continue;
            }
            const FString RootKey = Class->GetPathName() + TEXT("::") + Property->GetName();
            if (SeenRoots.Contains(RootKey))
            {
                continue;
            }
            SeenRoots.Add(RootKey);
            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
            {
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Owner, StaticIndex);
                const FString Path = Property->GetName() +
                    (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                CollectGameplayCameraObjectReferences(Property, ValuePtr, Path, 0, Out);
            }
        }
    }

    Out.Sort([](const FGameplayCameraObjectReference& A, const FGameplayCameraObjectReference& B)
    {
        if (A.PropertyPath != B.PropertyPath)
        {
            return A.PropertyPath < B.PropertyPath;
        }
        return (A.Target ? A.Target->GetPathName() : FString()) < (B.Target ? B.Target->GetPathName() : FString());
    });
}

static bool WriteGameplayCameraRigReferences(
    const FString& AssetPath,
    UObject* Owner,
    const FString& OwnerKind,
    int32& OutCount)
{
    OutCount = 0;
    if (!Owner)
    {
        return true;
    }
    TArray<FGameplayCameraObjectReference> References;
    GatherGameplayCameraReferences(Owner, References);
    TSet<FString> Seen;
    for (const FGameplayCameraObjectReference& Reference : References)
    {
        if (!Reference.Target || !IsGameplayCameraRigClass(Reference.Target->GetClass()))
        {
            continue;
        }
        const FString Key = Reference.PropertyPath + TEXT("\x1f") + Reference.Target->GetPathName();
        if (Seen.Contains(Key))
        {
            continue;
        }
        Seen.Add(Key);
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetStringField(TEXT("source_owner_path"), Owner->GetPathName());
        Row->SetStringField(TEXT("source_owner_kind"), OwnerKind);
        Row->SetStringField(TEXT("property_path"), Reference.PropertyPath);
        Row->SetStringField(TEXT("target_rig_path"), Reference.Target->GetPathName());
        Row->SetStringField(TEXT("target_rig_class"), Reference.Target->GetClass()->GetPathName());
        if (!GGameplayCameraWriters.RigReferences.Write(Row))
        {
            return false;
        }
        ++GGameplayCameraCounts.RigReferences;
        ++OutCount;
    }
    return true;
}

static bool WriteGameplayCameraTransitionState(
    const FString& AssetPath,
    UObject* Transition,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Transition)
    {
        return true;
    }
    if (!WriteObjectState(Transition, AssetPath, TEXT("gameplay_camera_transition"), Writers, Counts, SeenStateOwners))
    {
        return false;
    }
    TArray<UObject*> Nested;
    GatherNestedObjects(Transition, Nested);
    for (UObject* Object : Nested)
    {
        if (!Object)
        {
            continue;
        }
        if (!WriteObjectState(Object, AssetPath, TEXT("gameplay_camera_transition_object"), Writers, Counts, SeenStateOwners))
        {
            return false;
        }
    }
    return true;
}

static bool WriteGameplayCameraTransitions(
    const FString& AssetPath,
    UObject* Owner,
    const FString& OwnerKind,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners,
    int32& OutEnterCount,
    int32& OutExitCount,
    int32& OutGraphObjectCount)
{
    OutEnterCount = 0;
    OutExitCount = 0;
    OutGraphObjectCount = 0;
    if (!Owner)
    {
        return true;
    }

    TSet<FString> MembershipKeys;
    auto EmitArray = [&](const FName PropertyName, const FString& Role, int32& Counter) -> bool
    {
        TArray<UObject*> Objects;
        GatherGameplayCameraObjectArray(Owner, PropertyName, Objects);
        for (int32 Index = 0; Index < Objects.Num(); ++Index)
        {
            UObject* Transition = Objects[Index];
            if (!Transition || !IsGameplayCameraTransitionClass(Transition->GetClass()))
            {
                continue;
            }
            const FString MembershipKey = Role + TEXT("\x1f") + Transition->GetPathName();
            MembershipKeys.Add(MembershipKey);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("asset_path"), AssetPath);
            Row->SetStringField(TEXT("owner_path"), Owner->GetPathName());
            Row->SetStringField(TEXT("owner_kind"), OwnerKind);
            Row->SetStringField(TEXT("transition_role"), Role);
            Row->SetNumberField(TEXT("transition_index"), Index);
            Row->SetStringField(TEXT("transition_path"), Transition->GetPathName());
            Row->SetStringField(TEXT("transition_class"), Transition->GetClass()->GetPathName());
            if (!GGameplayCameraWriters.Transitions.Write(Row))
            {
                return false;
            }
            ++GGameplayCameraCounts.Transitions;
            ++Counter;
            if (!WriteGameplayCameraTransitionState(AssetPath, Transition, Writers, Counts, SeenStateOwners))
            {
                return false;
            }
            int32 Ignored = 0;
            if (!WriteGameplayCameraRigReferences(AssetPath, Transition, TEXT("gameplay_camera_transition"), Ignored))
            {
                return false;
            }
        }
        return true;
    };

    if (!EmitArray(FName(TEXT("EnterTransitions")), TEXT("enter"), OutEnterCount) ||
        !EmitArray(FName(TEXT("ExitTransitions")), TEXT("exit"), OutExitCount))
    {
        return false;
    }

    TArray<UObject*> GraphObjects;
    GatherGameplayCameraObjectArray(Owner, FName(TEXT("AllTransitionsObjects")), GraphObjects);
    if (GraphObjects.IsEmpty())
    {
        GatherGameplayCameraObjectArray(Owner, FName(TEXT("AllSharedTransitionsObjects")), GraphObjects);
    }
    int32 GraphIndex = 0;
    for (UObject* Transition : GraphObjects)
    {
        if (!Transition || !IsGameplayCameraTransitionClass(Transition->GetClass()))
        {
            continue;
        }
        const bool bAlreadyMember = MembershipKeys.Contains(TEXT("enter\x1f") + Transition->GetPathName()) ||
            MembershipKeys.Contains(TEXT("exit\x1f") + Transition->GetPathName());
        if (bAlreadyMember)
        {
            continue;
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetStringField(TEXT("owner_path"), Owner->GetPathName());
        Row->SetStringField(TEXT("owner_kind"), OwnerKind);
        Row->SetStringField(TEXT("transition_role"), TEXT("graph_object"));
        Row->SetNumberField(TEXT("transition_index"), GraphIndex++);
        Row->SetStringField(TEXT("transition_path"), Transition->GetPathName());
        Row->SetStringField(TEXT("transition_class"), Transition->GetClass()->GetPathName());
        if (!GGameplayCameraWriters.Transitions.Write(Row))
        {
            return false;
        }
        ++GGameplayCameraCounts.Transitions;
        ++OutGraphObjectCount;
        if (!WriteGameplayCameraTransitionState(AssetPath, Transition, Writers, Counts, SeenStateOwners))
        {
            return false;
        }
        int32 Ignored = 0;
        if (!WriteGameplayCameraRigReferences(AssetPath, Transition, TEXT("gameplay_camera_transition"), Ignored))
        {
            return false;
        }
    }
    return true;
}

static bool ScanGameplayCameraRig(
    UObject* Rig,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Rig || !IsGameplayCameraRigClass(Rig->GetClass()))
    {
        return true;
    }
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    UObject* RootNode = GetObjectField(Rig, FName(TEXT("RootNode")));

    TMap<FString, UObject*> NodeByPath;
    TArray<UObject*> GraphObjects;
    GatherGameplayCameraObjectArray(Rig, FName(TEXT("AllNodeTreeObjects")), GraphObjects);
    for (UObject* Object : GraphObjects)
    {
        if (Object && IsGameplayCameraNodeClass(Object->GetClass()))
        {
            NodeByPath.FindOrAdd(Object->GetPathName()) = Object;
        }
    }
    TArray<UObject*> Nested;
    GatherNestedObjects(Rig, Nested);
    for (UObject* Object : Nested)
    {
        if (Object && IsGameplayCameraNodeClass(Object->GetClass()))
        {
            NodeByPath.FindOrAdd(Object->GetPathName()) = Object;
        }
    }
    if (RootNode && IsGameplayCameraNodeClass(RootNode->GetClass()))
    {
        NodeByPath.FindOrAdd(RootNode->GetPathName()) = RootNode;
    }

    TArray<FString> NodePaths;
    NodeByPath.GetKeys(NodePaths);
    NodePaths.Sort();
    int32 NodeEdgeCount = 0;
    for (int32 Index = 0; Index < NodePaths.Num(); ++Index)
    {
        UObject* Node = NodeByPath[NodePaths[Index]];
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("rig_path"), AssetPath);
        Row->SetNumberField(TEXT("node_index"), Index);
        Row->SetStringField(TEXT("node_path"), Node->GetPathName());
        Row->SetStringField(TEXT("node_name"), Node->GetName());
        Row->SetStringField(TEXT("node_class"), Node->GetClass()->GetPathName());
        Row->SetBoolField(TEXT("is_root"), RootNode == Node);
        if (!GGameplayCameraWriters.Nodes.Write(Row))
        {
            return false;
        }
        ++GGameplayCameraCounts.Nodes;
        if (!WriteObjectState(Node, AssetPath, TEXT("gameplay_camera_node"), Writers, Counts, SeenStateOwners))
        {
            return false;
        }

        TArray<FGameplayCameraObjectReference> References;
        GatherGameplayCameraReferences(Node, References);
        TSet<FString> SeenEdges;
        for (const FGameplayCameraObjectReference& Reference : References)
        {
            if (!Reference.Target || !IsGameplayCameraNodeClass(Reference.Target->GetClass()) || Reference.Target == Node)
            {
                continue;
            }
            const FString EdgeKey = Reference.PropertyPath + TEXT("\x1f") + Reference.Target->GetPathName();
            if (SeenEdges.Contains(EdgeKey))
            {
                continue;
            }
            SeenEdges.Add(EdgeKey);
            TSharedRef<FJsonObject> Edge = MakeShared<FJsonObject>();
            Edge->SetStringField(TEXT("rig_path"), AssetPath);
            Edge->SetStringField(TEXT("source_node_path"), Node->GetPathName());
            Edge->SetStringField(TEXT("property_path"), Reference.PropertyPath);
            Edge->SetStringField(TEXT("target_node_path"), Reference.Target->GetPathName());
            Edge->SetStringField(TEXT("target_node_class"), Reference.Target->GetClass()->GetPathName());
            if (!GGameplayCameraWriters.NodeEdges.Write(Edge))
            {
                return false;
            }
            ++GGameplayCameraCounts.NodeEdges;
            ++NodeEdgeCount;
        }
        int32 Ignored = 0;
        if (!WriteGameplayCameraRigReferences(AssetPath, Node, TEXT("gameplay_camera_node"), Ignored))
        {
            return false;
        }
    }

    int32 EnterCount = 0;
    int32 ExitCount = 0;
    int32 LooseTransitionCount = 0;
    if (!WriteGameplayCameraTransitions(
            AssetPath,
            Rig,
            TEXT("gameplay_camera_rig"),
            Writers,
            Counts,
            SeenStateOwners,
            EnterCount,
            ExitCount,
            LooseTransitionCount))
    {
        return false;
    }

    int32 RigReferenceCount = 0;
    if (!WriteGameplayCameraRigReferences(AssetPath, Rig, TEXT("gameplay_camera_rig"), RigReferenceCount))
    {
        return false;
    }

    TSharedRef<FJsonObject> RigRow = MakeShared<FJsonObject>();
    RigRow->SetStringField(TEXT("rig_path"), AssetPath);
    RigRow->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    RigRow->SetStringField(TEXT("class_path"), Rig->GetClass()->GetPathName());
    RigRow->SetStringField(TEXT("root_node_path"), RootNode ? RootNode->GetPathName() : FString());
    RigRow->SetStringField(TEXT("root_node_class"), RootNode ? RootNode->GetClass()->GetPathName() : FString());
    RigRow->SetStringField(TEXT("initial_orientation"), ExportField(Rig, FName(TEXT("InitialOrientation"))));
    RigRow->SetStringField(TEXT("gameplay_tags"), ExportField(Rig, FName(TEXT("GameplayTags"))));
    RigRow->SetNumberField(TEXT("node_count"), NodePaths.Num());
    RigRow->SetNumberField(TEXT("node_edge_count"), NodeEdgeCount);
    RigRow->SetNumberField(TEXT("enter_transition_count"), EnterCount);
    RigRow->SetNumberField(TEXT("exit_transition_count"), ExitCount);
    RigRow->SetNumberField(TEXT("loose_transition_count"), LooseTransitionCount);
    RigRow->SetNumberField(TEXT("rig_reference_count"), RigReferenceCount);
    if (!GGameplayCameraWriters.Rigs.Write(RigRow))
    {
        return false;
    }
    ++GGameplayCameraCounts.Rigs;
    return true;
}

static bool ScanGameplayCameraAsset(
    UObject* CameraAsset,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!CameraAsset || !ClassInheritsName(CameraAsset->GetClass(), TEXT("CameraAsset")))
    {
        return true;
    }
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    UObject* Director = GetObjectField(CameraAsset, FName(TEXT("CameraDirector")));

    int32 DirectorRigReferences = 0;
    int32 DirectorNestedCount = 0;
    if (Director && IsGameplayCameraDirectorClass(Director->GetClass()))
    {
        TArray<UObject*> Nested;
        GatherNestedObjects(Director, Nested);
        DirectorNestedCount = Nested.Num();
        if (!WriteObjectState(Director, AssetPath, TEXT("gameplay_camera_director"), Writers, Counts, SeenStateOwners) ||
            !WriteGameplayCameraRigReferences(AssetPath, Director, TEXT("gameplay_camera_director"), DirectorRigReferences))
        {
            return false;
        }
        for (UObject* Object : Nested)
        {
            if (!Object)
            {
                continue;
            }
            if (!WriteObjectState(Object, AssetPath, TEXT("gameplay_camera_director_object"), Writers, Counts, SeenStateOwners))
            {
                return false;
            }
            int32 NestedRefs = 0;
            if (!WriteGameplayCameraRigReferences(AssetPath, Object, TEXT("gameplay_camera_director_object"), NestedRefs))
            {
                return false;
            }
            DirectorRigReferences += NestedRefs;
        }

        TSharedRef<FJsonObject> DirectorRow = MakeShared<FJsonObject>();
        DirectorRow->SetStringField(TEXT("asset_path"), AssetPath);
        DirectorRow->SetStringField(TEXT("director_path"), Director->GetPathName());
        DirectorRow->SetStringField(TEXT("director_class"), Director->GetClass()->GetPathName());
        DirectorRow->SetStringField(TEXT("run_in_editor"), ExportField(Director, FName(TEXT("bRunInEditor"))));
        DirectorRow->SetNumberField(TEXT("nested_object_count"), DirectorNestedCount);
        DirectorRow->SetNumberField(TEXT("rig_reference_count"), DirectorRigReferences);
        if (!GGameplayCameraWriters.Directors.Write(DirectorRow))
        {
            return false;
        }
        ++GGameplayCameraCounts.Directors;
    }

    int32 EnterCount = 0;
    int32 ExitCount = 0;
    int32 LooseTransitionCount = 0;
    if (!WriteGameplayCameraTransitions(
            AssetPath,
            CameraAsset,
            TEXT("gameplay_camera_asset"),
            Writers,
            Counts,
            SeenStateOwners,
            EnterCount,
            ExitCount,
            LooseTransitionCount))
    {
        return false;
    }

    int32 AssetRigReferences = 0;
    if (!WriteGameplayCameraRigReferences(AssetPath, CameraAsset, TEXT("gameplay_camera_asset"), AssetRigReferences))
    {
        return false;
    }

    TSharedRef<FJsonObject> AssetRow = MakeShared<FJsonObject>();
    AssetRow->SetStringField(TEXT("camera_asset_path"), AssetPath);
    AssetRow->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    AssetRow->SetStringField(TEXT("class_path"), CameraAsset->GetClass()->GetPathName());
    AssetRow->SetStringField(TEXT("director_path"), Director ? Director->GetPathName() : FString());
    AssetRow->SetStringField(TEXT("director_class"), Director ? Director->GetClass()->GetPathName() : FString());
    AssetRow->SetNumberField(TEXT("enter_transition_count"), EnterCount);
    AssetRow->SetNumberField(TEXT("exit_transition_count"), ExitCount);
    AssetRow->SetNumberField(TEXT("loose_transition_count"), LooseTransitionCount);
    AssetRow->SetNumberField(TEXT("asset_rig_reference_count"), AssetRigReferences);
    AssetRow->SetNumberField(TEXT("director_rig_reference_count"), DirectorRigReferences);
    if (!GGameplayCameraWriters.Assets.Write(AssetRow))
    {
        return false;
    }
    ++GGameplayCameraCounts.Assets;
    return true;
}

static bool ScanGameplayCameraProjectModel(
    const TArray<FAssetData>& Assets,
    const FString& ProjectDir,
    bool bIncludeEngine,
    bool bIncludeSelf,
    const FString& ToolPluginDir,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners,
    FString& OutError)
{
    for (const FAssetData& Asset : Assets)
    {
        const FString ClassPath = Asset.AssetClassPath.ToString();
        if (!IsGameplayCameraAssetClassPath(ClassPath))
        {
            continue;
        }

        FString PackageFilename;
        const bool bHasDiskPackage = FPackageName::DoesPackageExist(
            Asset.PackageName.ToString(),
            &PackageFilename,
            false);
        if (!bIncludeSelf && bHasDiskPackage && !ToolPluginDir.IsEmpty() &&
            IsInsideDirectory(PackageFilename, ToolPluginDir))
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
        const bool bCameraAsset = ClassPath == TEXT("/Script/GameplayCameras.CameraAsset");
        const FString Kind = bCameraAsset ? TEXT("gameplay_camera_asset") : TEXT("gameplay_camera_rig");

        TSharedRef<FJsonObject> SystemsRow = MakeShared<FJsonObject>();
        SystemsRow->SetStringField(TEXT("systems_path"), AssetPath);
        SystemsRow->SetStringField(TEXT("systems_kind"), Kind);
        SystemsRow->SetStringField(TEXT("family"), TEXT("gameplay_camera"));
        SystemsRow->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
        SystemsRow->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
        if (!Writers.Assets.Write(SystemsRow))
        {
            OutError = TEXT("failed writing Gameplay Cameras systems asset ") + AssetPath;
            return false;
        }
        ++Counts.Assets;
        if (!WriteObjectState(Object, AssetPath, Kind, Writers, Counts, SeenStateOwners))
        {
            OutError = TEXT("failed writing Gameplay Cameras state for ") + AssetPath;
            return false;
        }

        const bool bOk = bCameraAsset
            ? ScanGameplayCameraAsset(Object, Asset, Writers, Counts, SeenStateOwners)
            : ScanGameplayCameraRig(Object, Asset, Writers, Counts, SeenStateOwners);
        if (!bOk)
        {
            OutError = TEXT("failed while scanning Gameplay Cameras asset ") + AssetPath;
            return false;
        }
    }
    return true;
}
