struct FMoverCounts
{
    int64 Blueprints = 0;
    int64 Components = 0;
    int64 Modes = 0;
    int64 Settings = 0;
    int64 Transitions = 0;
};

struct FMoverWriters
{
    FJsonlWriter Blueprints;
    FJsonlWriter Components;
    FJsonlWriter Modes;
    FJsonlWriter Settings;
    FJsonlWriter Transitions;

    bool Open(const FString& OutputDir)
    {
        return Blueprints.Open(FPaths::Combine(OutputDir, TEXT("mover_blueprints.jsonl"))) &&
            Components.Open(FPaths::Combine(OutputDir, TEXT("mover_components.jsonl"))) &&
            Modes.Open(FPaths::Combine(OutputDir, TEXT("mover_modes.jsonl"))) &&
            Settings.Open(FPaths::Combine(OutputDir, TEXT("mover_settings.jsonl"))) &&
            Transitions.Open(FPaths::Combine(OutputDir, TEXT("mover_transitions.jsonl")));
    }
};

static FMoverCounts GMoverCounts;
static FMoverWriters GMoverWriters;

static bool IsMoverNativeClassPath(const FString& ClassPath)
{
    return ClassPath.StartsWith(TEXT("/Script/Mover."), ESearchCase::CaseSensitive) ||
        ClassPath.StartsWith(TEXT("/Script/ChaosMover."), ESearchCase::CaseSensitive);
}

static bool IsMoverClass(const UClass* Class)
{
    for (const UClass* It = Class; It; It = It->GetSuperClass())
    {
        if (IsMoverNativeClassPath(It->GetPathName()))
        {
            return true;
        }
    }
    return false;
}

static FString MoverBlueprintKind(const UClass* GeneratedClass)
{
    if (ClassInheritsName(GeneratedClass, TEXT("BaseMovementModeTransition")))
    {
        return TEXT("movement_transition");
    }
    if (ClassInheritsName(GeneratedClass, TEXT("BaseMovementMode")))
    {
        return TEXT("movement_mode");
    }
    return TEXT("mover_blueprint");
}

static FString MoverComponentKind(const UClass* Class)
{
    if (ClassInheritsName(Class, TEXT("CharacterMoverComponent")))
    {
        return TEXT("character_mover");
    }
    if (ClassInheritsName(Class, TEXT("NavMoverComponent")))
    {
        return TEXT("nav_mover");
    }
    if (ClassInheritsName(Class, TEXT("ChaosPathedMovementControllerComponent")))
    {
        return TEXT("chaos_pathed_movement_controller");
    }
    if (ClassInheritsName(Class, TEXT("MoverComponent")))
    {
        return TEXT("mover");
    }
    return TEXT("mover_component");
}

static FString ObjectTargetClass(UObject* Object)
{
    if (!Object)
    {
        return FString();
    }
    if (UClass* ClassObject = Cast<UClass>(Object))
    {
        return ClassObject->GetPathName();
    }
    return Object->GetClass()->GetPathName();
}

static FString ObjectTargetKind(UObject* Object)
{
    return Cast<UClass>(Object) ? TEXT("class") : TEXT("object");
}

static FString BlueprintPathForGeneratedClass(const FString& ClassPath)
{
    if (!ClassPath.StartsWith(TEXT("/Game/")) && !ClassPath.StartsWith(TEXT("/Plugin/")))
    {
        return FString();
    }
    const int32 DotIndex = ClassPath.Find(TEXT("."), ESearchCase::CaseSensitive, ESearchDir::FromEnd);
    if (DotIndex == INDEX_NONE)
    {
        return FString();
    }
    FString ObjectName = ClassPath.Mid(DotIndex + 1);
    if (!ObjectName.EndsWith(TEXT("_C"), ESearchCase::CaseSensitive))
    {
        return FString();
    }
    ObjectName.LeftChopInline(2, EAllowShrinking::No);
    return ClassPath.Left(DotIndex + 1) + ObjectName;
}

struct FMoverNamedObject
{
    FString Name;
    UObject* Object = nullptr;
};

static void GatherNamedObjectMap(UObject* Owner, const FName PropertyName, TArray<FMoverNamedObject>& Out)
{
    Out.Reset();
    if (!Owner)
    {
        return;
    }
    const FMapProperty* MapProperty = CastField<FMapProperty>(Owner->GetClass()->FindPropertyByName(PropertyName));
    if (!MapProperty)
    {
        return;
    }
    const FNameProperty* KeyProperty = CastField<FNameProperty>(MapProperty->KeyProp);
    const FObjectPropertyBase* ValueProperty = CastField<FObjectPropertyBase>(MapProperty->ValueProp);
    if (!KeyProperty || !ValueProperty)
    {
        return;
    }
    const void* MapValue = MapProperty->ContainerPtrToValuePtr<void>(Owner);
    if (!MapValue)
    {
        return;
    }
    FScriptMapHelper Helper(MapProperty, MapValue);
    for (int32 Index = 0; Index < Helper.GetMaxIndex(); ++Index)
    {
        if (!Helper.IsValidIndex(Index))
        {
            continue;
        }
        UObject* Value = ValueProperty->GetObjectPropertyValue(Helper.GetValuePtr(Index));
        if (!Value)
        {
            continue;
        }
        FMoverNamedObject Item;
        Item.Name = KeyProperty->GetPropertyValue(Helper.GetKeyPtr(Index)).ToString();
        Item.Object = Value;
        Out.Add(MoveTemp(Item));
    }
    Out.Sort([](const FMoverNamedObject& A, const FMoverNamedObject& B)
    {
        if (A.Name != B.Name)
        {
            return A.Name < B.Name;
        }
        return (A.Object ? A.Object->GetPathName() : FString()) <
            (B.Object ? B.Object->GetPathName() : FString());
    });
}

static void GatherObjectArray(UObject* Owner, const FName PropertyName, TArray<UObject*>& Out)
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

static bool WriteMoverSettings(
    const FString& AssetPath,
    UObject* Owner,
    const FString& OwnerKind,
    const FName PropertyName,
    const FString& Relation,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners,
    int32& OutCount)
{
    OutCount = 0;
    TArray<UObject*> Objects;
    GatherObjectArray(Owner, PropertyName, Objects);
    for (int32 Index = 0; Index < Objects.Num(); ++Index)
    {
        UObject* Target = Objects[Index];
        if (!Target)
        {
            continue;
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetStringField(TEXT("owner_path"), Owner->GetPathName());
        Row->SetStringField(TEXT("owner_kind"), OwnerKind);
        Row->SetStringField(TEXT("relation"), Relation);
        Row->SetNumberField(TEXT("setting_index"), Index);
        Row->SetStringField(TEXT("setting_path"), Target->GetPathName());
        Row->SetStringField(TEXT("setting_class"), ObjectTargetClass(Target));
        Row->SetStringField(TEXT("setting_asset_path"), BlueprintPathForGeneratedClass(ObjectTargetClass(Target)));
        Row->SetStringField(TEXT("target_kind"), ObjectTargetKind(Target));
        if (!GMoverWriters.Settings.Write(Row))
        {
            return false;
        }
        ++GMoverCounts.Settings;
        ++OutCount;
        if (!Cast<UClass>(Target) && !WriteObjectState(
                Target,
                AssetPath,
                Relation,
                Writers,
                Counts,
                SeenStateOwners))
        {
            return false;
        }
    }
    return true;
}

static bool WriteMoverTransitions(
    const FString& AssetPath,
    UObject* Owner,
    const FString& OwnerKind,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners,
    int32& OutCount)
{
    OutCount = 0;
    TArray<UObject*> Objects;
    GatherObjectArray(Owner, FName(TEXT("Transitions")), Objects);
    for (int32 Index = 0; Index < Objects.Num(); ++Index)
    {
        UObject* Target = Objects[Index];
        if (!Target)
        {
            continue;
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetStringField(TEXT("owner_path"), Owner->GetPathName());
        Row->SetStringField(TEXT("owner_kind"), OwnerKind);
        Row->SetNumberField(TEXT("transition_index"), Index);
        Row->SetStringField(TEXT("transition_path"), Target->GetPathName());
        Row->SetStringField(TEXT("transition_class"), ObjectTargetClass(Target));
        Row->SetStringField(TEXT("transition_asset_path"), BlueprintPathForGeneratedClass(ObjectTargetClass(Target)));
        Row->SetStringField(TEXT("target_kind"), ObjectTargetKind(Target));
        if (!GMoverWriters.Transitions.Write(Row))
        {
            return false;
        }
        ++GMoverCounts.Transitions;
        ++OutCount;
        if (!Cast<UClass>(Target) && !WriteObjectState(
                Target,
                AssetPath,
                TEXT("mover_transition"),
                Writers,
                Counts,
                SeenStateOwners))
        {
            return false;
        }
    }
    return true;
}

static bool ScanMoverComponent(
    const FString& BlueprintPath,
    const FString& ComponentName,
    UObject* Component,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Component || !IsMoverClass(Component->GetClass()))
    {
        return true;
    }

    const FString ComponentKind = MoverComponentKind(Component->GetClass());
    const FString StartingMode = GetNameField(
        Component->GetClass(), Component, FName(TEXT("StartingMovementMode")), Component);
    UObject* BackendObject = GetObjectField(Component, FName(TEXT("BackendClass")));
    const FString BackendClass = ObjectTargetClass(BackendObject);
    const FString SyncInputs = ExportField(Component, FName(TEXT("bSyncInputsForSimProxy")));

    TArray<FMoverNamedObject> Modes;
    GatherNamedObjectMap(Component, FName(TEXT("MovementModes")), Modes);

    int32 SharedSettingsCount = 0;
    if (!WriteMoverSettings(
            BlueprintPath,
            Component,
            TEXT("mover_component"),
            FName(TEXT("SharedSettings")),
            TEXT("shared_setting"),
            Writers,
            Counts,
            SeenStateOwners,
            SharedSettingsCount))
    {
        return false;
    }

    int32 TransitionCount = 0;
    if (!WriteMoverTransitions(
            BlueprintPath,
            Component,
            TEXT("mover_component"),
            Writers,
            Counts,
            SeenStateOwners,
            TransitionCount))
    {
        return false;
    }

    TSharedRef<FJsonObject> ComponentRow = MakeShared<FJsonObject>();
    ComponentRow->SetStringField(TEXT("blueprint_path"), BlueprintPath);
    ComponentRow->SetStringField(TEXT("component_path"), Component->GetPathName());
    ComponentRow->SetStringField(TEXT("component_name"), ComponentName);
    ComponentRow->SetStringField(TEXT("component_class"), Component->GetClass()->GetPathName());
    ComponentRow->SetStringField(TEXT("component_kind"), ComponentKind);
    ComponentRow->SetStringField(TEXT("backend_class"), BackendClass);
    ComponentRow->SetStringField(TEXT("starting_movement_mode"), StartingMode);
    ComponentRow->SetStringField(TEXT("sync_inputs_for_sim_proxy"), SyncInputs);
    ComponentRow->SetNumberField(TEXT("mode_count"), Modes.Num());
    ComponentRow->SetNumberField(TEXT("shared_setting_count"), SharedSettingsCount);
    ComponentRow->SetNumberField(TEXT("transition_count"), TransitionCount);
    if (!GMoverWriters.Components.Write(ComponentRow))
    {
        return false;
    }
    ++GMoverCounts.Components;

    if (!WriteObjectState(
            Component,
            BlueprintPath,
            TEXT("mover_component"),
            Writers,
            Counts,
            SeenStateOwners))
    {
        return false;
    }

    for (int32 Index = 0; Index < Modes.Num(); ++Index)
    {
        const FMoverNamedObject& Mode = Modes[Index];
        if (!Mode.Object)
        {
            continue;
        }
        const FString ModeClass = Mode.Object->GetClass()->GetPathName();
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("blueprint_path"), BlueprintPath);
        Row->SetStringField(TEXT("component_path"), Component->GetPathName());
        Row->SetNumberField(TEXT("mode_index"), Index);
        Row->SetStringField(TEXT("mode_name"), Mode.Name);
        Row->SetStringField(TEXT("mode_path"), Mode.Object->GetPathName());
        Row->SetStringField(TEXT("mode_class"), ModeClass);
        Row->SetStringField(TEXT("mode_asset_path"), BlueprintPathForGeneratedClass(ModeClass));
        Row->SetBoolField(TEXT("is_starting"), !StartingMode.IsEmpty() && Mode.Name == StartingMode);
        if (!GMoverWriters.Modes.Write(Row))
        {
            return false;
        }
        ++GMoverCounts.Modes;

        if (!WriteObjectState(
                Mode.Object,
                BlueprintPath,
                TEXT("mover_mode"),
                Writers,
                Counts,
                SeenStateOwners))
        {
            return false;
        }

        int32 Ignored = 0;
        if (!WriteMoverSettings(
                BlueprintPath,
                Mode.Object,
                TEXT("mover_mode"),
                FName(TEXT("SharedSettingsClasses")),
                TEXT("shared_setting_class"),
                Writers,
                Counts,
                SeenStateOwners,
                Ignored) ||
            !WriteMoverTransitions(
                BlueprintPath,
                Mode.Object,
                TEXT("mover_mode"),
                Writers,
                Counts,
                SeenStateOwners,
                Ignored))
        {
            return false;
        }
    }

    return true;
}

static bool ScanMoverBlueprintAsset(
    UBlueprint* Blueprint,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners,
    bool& bOutFoundMover)
{
    bOutFoundMover = false;
    if (!Blueprint || !Blueprint->GeneratedClass)
    {
        return true;
    }

    const FString BlueprintPath = Asset.GetSoftObjectPath().ToString();
    UClass* GeneratedClass = Blueprint->GeneratedClass;
    const bool bMoverDerived = IsMoverClass(GeneratedClass);

    TMap<FString, UObject*> ComponentTemplates;
    if (Blueprint->SimpleConstructionScript)
    {
        for (USCS_Node* Node : Blueprint->SimpleConstructionScript->GetAllNodes())
        {
            if (!Node || !Node->ComponentTemplate || !IsMoverClass(Node->ComponentTemplate->GetClass()))
            {
                continue;
            }
            const FString Key = Node->ComponentTemplate->GetPathName();
            ComponentTemplates.FindOrAdd(Key) = Node->ComponentTemplate;
        }
    }

    if (UObject* CDO = GeneratedClass->GetDefaultObject(false))
    {
        TArray<UObject*> Nested;
        GetObjectsWithOuter(
            CDO,
            Nested,
            EGetObjectsFlags::IncludeNestedObjects,
            RF_Transient,
            EInternalObjectFlags::Garbage);
        for (UObject* Object : Nested)
        {
            if (UActorComponent* Component = Cast<UActorComponent>(Object))
            {
                if (IsMoverClass(Component->GetClass()))
                {
                    ComponentTemplates.FindOrAdd(Component->GetPathName()) = Component;
                }
            }
        }
    }

    TArray<FString> ComponentPaths;
    ComponentTemplates.GetKeys(ComponentPaths);
    ComponentPaths.Sort();
    for (const FString& ComponentPath : ComponentPaths)
    {
        UObject* Component = ComponentTemplates.FindRef(ComponentPath);
        if (!Component)
        {
            continue;
        }
        FString ComponentName = Component->GetName();
        if (Blueprint->SimpleConstructionScript)
        {
            for (USCS_Node* Node : Blueprint->SimpleConstructionScript->GetAllNodes())
            {
                if (Node && Node->ComponentTemplate == Component)
                {
                    ComponentName = Node->GetVariableName().ToString();
                    break;
                }
            }
        }
        if (!ScanMoverComponent(
                BlueprintPath,
                ComponentName,
                Component,
                Writers,
                Counts,
                SeenStateOwners))
        {
            return false;
        }
        bOutFoundMover = true;
    }

    if (!bMoverDerived)
    {
        return true;
    }

    bOutFoundMover = true;
    UObject* CDO = GeneratedClass->GetDefaultObject(false);
    const FString Kind = MoverBlueprintKind(GeneratedClass);
    int32 SharedSettingsClassCount = 0;
    int32 TransitionCount = 0;
    if (CDO)
    {
        if (!WriteObjectState(
                CDO,
                BlueprintPath,
                Kind == TEXT("movement_mode") ? TEXT("mover_mode_blueprint") : TEXT("mover_transition_blueprint"),
                Writers,
                Counts,
                SeenStateOwners) ||
            !WriteMoverSettings(
                BlueprintPath,
                CDO,
                Kind,
                FName(TEXT("SharedSettingsClasses")),
                TEXT("shared_setting_class"),
                Writers,
                Counts,
                SeenStateOwners,
                SharedSettingsClassCount) ||
            !WriteMoverTransitions(
                BlueprintPath,
                CDO,
                Kind,
                Writers,
                Counts,
                SeenStateOwners,
                TransitionCount))
        {
            return false;
        }
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("blueprint_path"), BlueprintPath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("mover_kind"), Kind);
    Row->SetStringField(TEXT("generated_class"), GeneratedClass->GetPathName());
    Row->SetStringField(
        TEXT("parent_class"),
        GeneratedClass->GetSuperClass() ? GeneratedClass->GetSuperClass()->GetPathName() : FString());
    Row->SetStringField(TEXT("cdo_path"), CDO ? CDO->GetPathName() : FString());
    Row->SetStringField(TEXT("cdo_class"), CDO ? CDO->GetClass()->GetPathName() : FString());
    Row->SetNumberField(TEXT("shared_setting_class_count"), SharedSettingsClassCount);
    Row->SetNumberField(TEXT("transition_count"), TransitionCount);
    if (!GMoverWriters.Blueprints.Write(Row))
    {
        return false;
    }
    ++GMoverCounts.Blueprints;
    return true;
}

static bool ScanMoverProjectModel(
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
        if (Asset.AssetClassPath != UBlueprint::StaticClass()->GetClassPathName())
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

        UBlueprint* Blueprint = Cast<UBlueprint>(Asset.GetAsset());
        if (!Blueprint)
        {
            continue;
        }
        bool bFoundMover = false;
        if (!ScanMoverBlueprintAsset(
                Blueprint,
                Asset,
                Writers,
                Counts,
                SeenStateOwners,
                bFoundMover))
        {
            OutError = TEXT("failed while scanning Mover Blueprint ") + Asset.GetSoftObjectPath().ToString();
            return false;
        }
    }
    return true;
}
