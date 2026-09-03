struct FNavigationCounts
{
    int64 Areas = 0;
    int64 AreaAgentMappings = 0;
    int64 Systems = 0;
    int64 Agents = 0;
    int64 LinkDefaults = 0;
    int64 ModifierDefaults = 0;
    int64 InvokerDefaults = 0;
    int64 BoundsDefaults = 0;
    int64 RecastDefaults = 0;
    int64 TruncatedValues = 0;
    int64 MissingExpectedClasses = 0;
};

struct FNavigationWriters
{
    FJsonlWriter Areas;
    FJsonlWriter AreaAgentMappings;
    FJsonlWriter Systems;
    FJsonlWriter Agents;
    FJsonlWriter LinkDefaults;
    FJsonlWriter ModifierDefaults;
    FJsonlWriter InvokerDefaults;
    FJsonlWriter BoundsDefaults;
    FJsonlWriter RecastDefaults;

    bool Open(const FString& OutputDir)
    {
        return Areas.Open(FPaths::Combine(OutputDir, TEXT("navigation_areas.jsonl"))) &&
            AreaAgentMappings.Open(FPaths::Combine(OutputDir, TEXT("navigation_area_agent_mappings.jsonl"))) &&
            Systems.Open(FPaths::Combine(OutputDir, TEXT("navigation_systems.jsonl"))) &&
            Agents.Open(FPaths::Combine(OutputDir, TEXT("navigation_agents.jsonl"))) &&
            LinkDefaults.Open(FPaths::Combine(OutputDir, TEXT("navigation_link_defaults.jsonl"))) &&
            ModifierDefaults.Open(FPaths::Combine(OutputDir, TEXT("navigation_modifier_defaults.jsonl"))) &&
            InvokerDefaults.Open(FPaths::Combine(OutputDir, TEXT("navigation_invoker_defaults.jsonl"))) &&
            BoundsDefaults.Open(FPaths::Combine(OutputDir, TEXT("navigation_bounds_defaults.jsonl"))) &&
            RecastDefaults.Open(FPaths::Combine(OutputDir, TEXT("navigation_recast_defaults.jsonl")));
    }
};

static FNavigationCounts GNavigationCounts;
static FNavigationWriters GNavigationWriters;
static constexpr int32 NavigationMaxExportChars = 65536;

static const TCHAR* NavigationExpectedClassPaths[] = {
    TEXT("/Script/NavigationSystem.NavArea"),
    TEXT("/Script/NavigationSystem.NavArea_Default"),
    TEXT("/Script/NavigationSystem.NavArea_Null"),
    TEXT("/Script/NavigationSystem.NavArea_Obstacle"),
    TEXT("/Script/NavigationSystem.NavigationSystemV1"),
    TEXT("/Script/Engine.NavigationSystemConfig"),
    TEXT("/Script/NavigationSystem.NavigationInvokerComponent"),
    TEXT("/Script/NavigationSystem.NavModifierComponent"),
    TEXT("/Script/NavigationSystem.NavModifierVolume"),
    TEXT("/Script/AIModule.NavLinkProxy"),
    TEXT("/Script/NavigationSystem.NavLinkCustomComponent"),
    TEXT("/Script/NavigationSystem.NavMeshBoundsVolume"),
    TEXT("/Script/NavigationSystem.RecastNavMesh"),
};

static UClass* NavigationLoadClass(const TCHAR* Path)
{
    return StaticLoadClass(UObject::StaticClass(), nullptr, Path);
}

static FString NavigationExportValue(UObject* Object, const FName PropertyName)
{
    if (!Object) return FString();
    const FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
    if (!Property) return FString();
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    if (!ValuePtr) return FString();
    FString Value;
    Property->ExportTextItem_Direct(Value, ValuePtr, nullptr, Object, PPF_None, nullptr);
    if (Value.Len() > NavigationMaxExportChars)
    {
        Value.LeftInline(NavigationMaxExportChars, EAllowShrinking::No);
        ++GNavigationCounts.TruncatedValues;
    }
    return Value;
}

static bool NavigationBoolValue(UObject* Object, const FName PropertyName, const bool DefaultValue = false)
{
    if (!Object) return DefaultValue;
    const FBoolProperty* Property = CastField<FBoolProperty>(Object->GetClass()->FindPropertyByName(PropertyName));
    if (!Property) return DefaultValue;
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    return ValuePtr ? Property->GetPropertyValue(ValuePtr) : DefaultValue;
}

static FString NavigationObjectPath(UObject* Object, const FName PropertyName)
{
    if (!Object) return FString();
    const FProperty* Property = Object->GetClass()->FindPropertyByName(PropertyName);
    if (!Property) return FString();
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    if (!ValuePtr) return FString();
    if (const FSoftObjectProperty* Soft = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* Ptr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        return Ptr && !Ptr->IsNull() ? Ptr->ToSoftObjectPath().ToString() : FString();
    }
    if (const FObjectPropertyBase* Obj = CastField<FObjectPropertyBase>(Property))
    {
        UObject* Target = Obj->GetObjectPropertyValue(ValuePtr);
        return Target ? Target->GetPathName() : FString();
    }
    return FString();
}

static FString NavigationStructExport(
    const UStruct* Struct,
    const void* StructPtr,
    const FName PropertyName,
    UObject* ExportOwner)
{
    if (!Struct || !StructPtr) return FString();
    const FProperty* Property = Struct->FindPropertyByName(PropertyName);
    if (!Property) return FString();
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructPtr);
    FString Value;
    Property->ExportTextItem_Direct(Value, ValuePtr, nullptr, ExportOwner, PPF_None, nullptr);
    if (Value.Len() > NavigationMaxExportChars)
    {
        Value.LeftInline(NavigationMaxExportChars, EAllowShrinking::No);
        ++GNavigationCounts.TruncatedValues;
    }
    return Value;
}

static bool NavigationStructBool(
    const UStruct* Struct,
    const void* StructPtr,
    const FName PropertyName,
    const bool DefaultValue = false)
{
    if (!Struct || !StructPtr) return DefaultValue;
    const FBoolProperty* Property = CastField<FBoolProperty>(Struct->FindPropertyByName(PropertyName));
    if (!Property) return DefaultValue;
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructPtr);
    return ValuePtr ? Property->GetPropertyValue(ValuePtr) : DefaultValue;
}

static FString NavigationStructObjectPath(
    const UStruct* Struct,
    const void* StructPtr,
    const FName PropertyName)
{
    if (!Struct || !StructPtr) return FString();
    const FProperty* Property = Struct->FindPropertyByName(PropertyName);
    if (!Property) return FString();
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructPtr);
    if (!ValuePtr) return FString();
    if (const FSoftObjectProperty* Soft = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* Ptr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        return Ptr && !Ptr->IsNull() ? Ptr->ToSoftObjectPath().ToString() : FString();
    }
    if (const FObjectPropertyBase* Obj = CastField<FObjectPropertyBase>(Property))
    {
        UObject* Target = Obj->GetObjectPropertyValue(ValuePtr);
        return Target ? Target->GetPathName() : FString();
    }
    return FString();
}

static TArray<TSharedPtr<FJsonValue>> NavigationSupportedAgentArray(
    const UStruct* Struct,
    const void* StructPtr)
{
    TArray<TSharedPtr<FJsonValue>> Values;
    if (!Struct || !StructPtr) return Values;
    for (int32 Index = 0; Index <= 30; ++Index)
    {
        const FName Name(*FString::Printf(TEXT("bSupportsAgent%d"), Index));
        const FBoolProperty* Property = CastField<FBoolProperty>(Struct->FindPropertyByName(Name));
        if (!Property) continue;
        const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructPtr);
        if (ValuePtr && Property->GetPropertyValue(ValuePtr))
            Values.Add(MakeShared<FJsonValueNumber>(Index));
    }
    return Values;
}

static TArray<TSharedPtr<FJsonValue>> NavigationSupportedAgents(UObject* Object, const FName PropertyName)
{
    TArray<TSharedPtr<FJsonValue>> Values;
    if (!Object) return Values;
    const FStructProperty* Property = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(PropertyName));
    if (!Property || !Property->Struct) return Values;
    const void* StructPtr = Property->ContainerPtrToValuePtr<void>(Object);
    return NavigationSupportedAgentArray(Property->Struct, StructPtr);
}

static FString NavigationNestedExport(UObject* Object, const FName RootProperty, const FName NestedProperty)
{
    if (!Object) return FString();
    const FStructProperty* Root = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(RootProperty));
    if (!Root || !Root->Struct) return FString();
    const void* RootPtr = Root->ContainerPtrToValuePtr<void>(Object);
    return NavigationStructExport(Root->Struct, RootPtr, NestedProperty, Object);
}

static FString NavigationNestedObjectPath(UObject* Object, const FName RootProperty, const FName NestedProperty)
{
    if (!Object) return FString();
    const FStructProperty* Root = CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(RootProperty));
    if (!Root || !Root->Struct) return FString();
    const void* RootPtr = Root->ContainerPtrToValuePtr<void>(Object);
    return NavigationStructObjectPath(Root->Struct, RootPtr, NestedProperty);
}

static FString NavigationAreaKind(const FString& ClassPath)
{
    if (ClassPath == TEXT("/Script/NavigationSystem.NavArea")) return TEXT("base");
    if (ClassPath == TEXT("/Script/NavigationSystem.NavAreaMeta")) return TEXT("meta");
    if (ClassPath == TEXT("/Script/NavigationSystem.NavAreaMeta_SwitchByAgent")) return TEXT("meta_switch_by_agent");
    if (ClassPath == TEXT("/Script/NavigationSystem.NavArea_Default")) return TEXT("default");
    if (ClassPath == TEXT("/Script/NavigationSystem.NavArea_LowHeight")) return TEXT("low_height");
    if (ClassPath == TEXT("/Script/NavigationSystem.NavArea_Null")) return TEXT("null");
    if (ClassPath == TEXT("/Script/NavigationSystem.NavArea_Obstacle")) return TEXT("obstacle");
    return TEXT("custom");
}

static bool NavigationWriteAreas(UClass* NavAreaBase)
{
    if (!NavAreaBase) return false;
    TMap<FString, UClass*> Classes;
    Classes.Add(NavAreaBase->GetPathName(), NavAreaBase);
    TArray<UClass*> Derived;
    GetDerivedClasses(NavAreaBase, Derived, true);
    for (UClass* Class : Derived)
        if (Class) Classes.Add(Class->GetPathName(), Class);

    TArray<FString> Paths;
    Classes.GetKeys(Paths);
    Paths.Sort([](const FString& A, const FString& B)
    {
        return FCString::Strcmp(*A, *B) < 0;
    });

    for (const FString& ClassPath : Paths)
    {
        UClass* Class = Classes[ClassPath];
        UObject* CDO = Class ? Class->GetDefaultObject() : nullptr;
        if (!CDO) return false;
        if (Class->HasAnyClassFlags(CLASS_Config)) CDO->LoadConfig();

        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("class_path"), ClassPath);
        Row->SetStringField(TEXT("parent_class"), Class->GetSuperClass() ? Class->GetSuperClass()->GetPathName() : FString());
        Row->SetStringField(TEXT("area_kind"), NavigationAreaKind(ClassPath));
        Row->SetStringField(TEXT("default_cost"), NavigationExportValue(CDO, TEXT("DefaultCost")));
        Row->SetStringField(TEXT("fixed_area_entering_cost"), NavigationExportValue(CDO, TEXT("FixedAreaEnteringCost")));
        Row->SetArrayField(TEXT("supported_agents"), NavigationSupportedAgents(CDO, TEXT("SupportedAgents")));
        if (!GNavigationWriters.Areas.Write(Row)) return false;
        ++GNavigationCounts.Areas;

        for (int32 AgentIndex = 0; AgentIndex <= 30; ++AgentIndex)
        {
            const FName PropertyName(*FString::Printf(TEXT("Agent%dArea"), AgentIndex));
            const FString Target = NavigationObjectPath(CDO, PropertyName);
            if (Target.IsEmpty()) continue;
            TSharedRef<FJsonObject> Mapping = MakeShared<FJsonObject>();
            Mapping->SetStringField(TEXT("source_area"), ClassPath);
            Mapping->SetNumberField(TEXT("agent_index"), AgentIndex);
            Mapping->SetStringField(TEXT("target_area"), Target);
            if (!GNavigationWriters.AreaAgentMappings.Write(Mapping)) return false;
            ++GNavigationCounts.AreaAgentMappings;
        }
    }
    return true;
}

static bool NavigationWriteSystem(UClass* Class, const FString& Kind, const bool bWriteAgents)
{
    if (!Class) return false;
    UObject* CDO = Class->GetDefaultObject();
    if (!CDO) return false;
    if (Class->HasAnyClassFlags(CLASS_Config)) CDO->LoadConfig();

    int32 AgentCount = 0;
    const FArrayProperty* AgentsProperty = bWriteAgents
        ? CastField<FArrayProperty>(Class->FindPropertyByName(TEXT("SupportedAgents")))
        : nullptr;
    const FStructProperty* AgentInner = AgentsProperty ? CastField<FStructProperty>(AgentsProperty->Inner) : nullptr;
    TUniquePtr<FScriptArrayHelper> AgentHelper;
    if (AgentsProperty && AgentInner && AgentInner->Struct)
    {
        void* ValuePtr = AgentsProperty->ContainerPtrToValuePtr<void>(CDO);
        AgentHelper = MakeUnique<FScriptArrayHelper>(AgentsProperty, ValuePtr);
        AgentCount = AgentHelper->Num();
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("class_path"), Class->GetPathName());
    Row->SetStringField(TEXT("system_kind"), Kind);
    Row->SetStringField(TEXT("default_agent_name"), NavigationExportValue(CDO, TEXT("DefaultAgentName")));
    Row->SetArrayField(TEXT("supported_agents"), NavigationSupportedAgents(CDO, TEXT("SupportedAgentsMask")));
    Row->SetBoolField(TEXT("generate_navigation_only_around_invokers"),
        NavigationBoolValue(CDO, TEXT("bGenerateNavigationOnlyAroundNavigationInvokers")));
    Row->SetBoolField(TEXT("skip_agent_height_check_when_picking_nav_data"),
        NavigationBoolValue(CDO, TEXT("bSkipAgentHeightCheckWhenPickingNavData")));
    Row->SetStringField(TEXT("crowd_manager_class"), NavigationObjectPath(CDO, TEXT("CrowdManagerClass")));
    Row->SetNumberField(TEXT("agent_count"), AgentCount);
    if (!GNavigationWriters.Systems.Write(Row)) return false;
    ++GNavigationCounts.Systems;

    if (!AgentHelper.IsValid() || !AgentInner || !AgentInner->Struct) return true;
    for (int32 Index = 0; Index < AgentHelper->Num(); ++Index)
    {
        const void* Agent = AgentHelper->GetRawPtr(Index);
        TSharedRef<FJsonObject> AgentRow = MakeShared<FJsonObject>();
        AgentRow->SetStringField(TEXT("system_class"), Class->GetPathName());
        AgentRow->SetNumberField(TEXT("agent_index"), Index);
        AgentRow->SetStringField(TEXT("name"), NavigationStructExport(AgentInner->Struct, Agent, TEXT("Name"), CDO));
        AgentRow->SetStringField(TEXT("nav_data_class"), NavigationStructObjectPath(AgentInner->Struct, Agent, TEXT("NavDataClass")));
        AgentRow->SetStringField(TEXT("preferred_nav_data"), NavigationStructObjectPath(AgentInner->Struct, Agent, TEXT("PreferredNavData")));
        AgentRow->SetStringField(TEXT("agent_radius"), NavigationStructExport(AgentInner->Struct, Agent, TEXT("AgentRadius"), CDO));
        AgentRow->SetStringField(TEXT("agent_height"), NavigationStructExport(AgentInner->Struct, Agent, TEXT("AgentHeight"), CDO));
        AgentRow->SetStringField(TEXT("agent_step_height"), NavigationStructExport(AgentInner->Struct, Agent, TEXT("AgentStepHeight"), CDO));
        AgentRow->SetStringField(TEXT("default_query_extent"), NavigationStructExport(AgentInner->Struct, Agent, TEXT("DefaultQueryExtent"), CDO));
        AgentRow->SetStringField(TEXT("nav_walking_search_height_scale"), NavigationStructExport(AgentInner->Struct, Agent, TEXT("NavWalkingSearchHeightScale"), CDO));
        AgentRow->SetBoolField(TEXT("can_crouch"), NavigationStructBool(AgentInner->Struct, Agent, TEXT("bCanCrouch")));
        AgentRow->SetBoolField(TEXT("can_jump"), NavigationStructBool(AgentInner->Struct, Agent, TEXT("bCanJump")));
        AgentRow->SetBoolField(TEXT("can_walk"), NavigationStructBool(AgentInner->Struct, Agent, TEXT("bCanWalk")));
        AgentRow->SetBoolField(TEXT("can_swim"), NavigationStructBool(AgentInner->Struct, Agent, TEXT("bCanSwim")));
        AgentRow->SetBoolField(TEXT("can_fly"), NavigationStructBool(AgentInner->Struct, Agent, TEXT("bCanFly")));
        if (!GNavigationWriters.Agents.Write(AgentRow)) return false;
        ++GNavigationCounts.Agents;
    }
    return true;
}

static bool NavigationWriteSimpleLinks(UClass* NavLinkProxyClass)
{
    if (!NavLinkProxyClass) return false;
    UObject* CDO = NavLinkProxyClass->GetDefaultObject();
    if (!CDO) return false;
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(NavLinkProxyClass->FindPropertyByName(TEXT("PointLinks")));
    const FStructProperty* Inner = ArrayProperty ? CastField<FStructProperty>(ArrayProperty->Inner) : nullptr;
    if (!ArrayProperty || !Inner || !Inner->Struct) return true;
    void* ValuePtr = ArrayProperty->ContainerPtrToValuePtr<void>(CDO);
    FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Link = Helper.GetRawPtr(Index);
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("link_id"), FString::Printf(TEXT("%s#SimpleLinkDefault:%d"), *NavLinkProxyClass->GetPathName(), Index));
        Row->SetStringField(TEXT("class_path"), NavLinkProxyClass->GetPathName());
        Row->SetStringField(TEXT("link_kind"), TEXT("simple"));
        Row->SetNumberField(TEXT("link_index"), Index);
        Row->SetStringField(TEXT("direction"), NavigationStructExport(Inner->Struct, Link, TEXT("Direction"), CDO));
        Row->SetStringField(TEXT("area_class"), NavigationStructObjectPath(Inner->Struct, Link, TEXT("AreaClass")));
        Row->SetStringField(TEXT("enabled_area_class"), FString());
        Row->SetStringField(TEXT("disabled_area_class"), FString());
        Row->SetStringField(TEXT("obstacle_area_class"), FString());
        const FStructProperty* SupportedProperty = CastField<FStructProperty>(Inner->Struct->FindPropertyByName(TEXT("SupportedAgents")));
        const void* SupportedPtr = SupportedProperty ? SupportedProperty->ContainerPtrToValuePtr<void>(Link) : nullptr;
        Row->SetArrayField(TEXT("supported_agents"),
            SupportedProperty ? NavigationSupportedAgentArray(SupportedProperty->Struct, SupportedPtr) : TArray<TSharedPtr<FJsonValue>>());
        Row->SetStringField(TEXT("left"), NavigationStructExport(Inner->Struct, Link, TEXT("Left"), CDO));
        Row->SetStringField(TEXT("right"), NavigationStructExport(Inner->Struct, Link, TEXT("Right"), CDO));
        Row->SetStringField(TEXT("left_project_height"), NavigationStructExport(Inner->Struct, Link, TEXT("LeftProjectHeight"), CDO));
        Row->SetStringField(TEXT("max_fall_down_length"), NavigationStructExport(Inner->Struct, Link, TEXT("MaxFallDownLength"), CDO));
        Row->SetStringField(TEXT("snap_radius"), NavigationStructExport(Inner->Struct, Link, TEXT("SnapRadius"), CDO));
        Row->SetStringField(TEXT("snap_height"), NavigationStructExport(Inner->Struct, Link, TEXT("SnapHeight"), CDO));
        Row->SetBoolField(TEXT("use_snap_height"), NavigationStructBool(Inner->Struct, Link, TEXT("bUseSnapHeight")));
        Row->SetBoolField(TEXT("snap_to_cheapest_area"), NavigationStructBool(Inner->Struct, Link, TEXT("bSnapToCheapestArea")));
        Row->SetBoolField(TEXT("smart_link_relevant"), NavigationBoolValue(CDO, TEXT("bSmartLinkIsRelevant")));
        if (!GNavigationWriters.LinkDefaults.Write(Row)) return false;
        ++GNavigationCounts.LinkDefaults;
    }
    return true;
}

static bool NavigationWriteSmartLink(UClass* SmartLinkClass, UClass* NavLinkProxyClass)
{
    if (!SmartLinkClass) return false;
    UObject* CDO = SmartLinkClass->GetDefaultObject();
    UObject* ProxyCDO = NavLinkProxyClass ? NavLinkProxyClass->GetDefaultObject() : nullptr;
    if (!CDO) return false;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("link_id"), SmartLinkClass->GetPathName() + TEXT("#SmartLinkDefault"));
    Row->SetStringField(TEXT("class_path"), SmartLinkClass->GetPathName());
    Row->SetStringField(TEXT("link_kind"), TEXT("smart"));
    Row->SetNumberField(TEXT("link_index"), -1);
    Row->SetStringField(TEXT("direction"), NavigationExportValue(CDO, TEXT("LinkDirection")));
    Row->SetStringField(TEXT("area_class"), FString());
    Row->SetStringField(TEXT("enabled_area_class"), NavigationObjectPath(CDO, TEXT("EnabledAreaClass")));
    Row->SetStringField(TEXT("disabled_area_class"), NavigationObjectPath(CDO, TEXT("DisabledAreaClass")));
    Row->SetStringField(TEXT("obstacle_area_class"), NavigationObjectPath(CDO, TEXT("ObstacleAreaClass")));
    Row->SetArrayField(TEXT("supported_agents"), NavigationSupportedAgents(CDO, TEXT("SupportedAgents")));
    Row->SetStringField(TEXT("left"), FString());
    Row->SetStringField(TEXT("right"), FString());
    Row->SetStringField(TEXT("left_project_height"), FString());
    Row->SetStringField(TEXT("max_fall_down_length"), FString());
    Row->SetStringField(TEXT("snap_radius"), FString());
    Row->SetStringField(TEXT("snap_height"), FString());
    Row->SetBoolField(TEXT("use_snap_height"), false);
    Row->SetBoolField(TEXT("snap_to_cheapest_area"), false);
    Row->SetBoolField(TEXT("smart_link_relevant"),
        ProxyCDO ? NavigationBoolValue(ProxyCDO, TEXT("bSmartLinkIsRelevant")) : false);
    if (!GNavigationWriters.LinkDefaults.Write(Row)) return false;
    ++GNavigationCounts.LinkDefaults;
    return true;
}

static bool NavigationWriteModifier(UClass* Class, const FString& Kind)
{
    if (!Class) return false;
    UObject* CDO = Class->GetDefaultObject();
    if (!CDO) return false;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("modifier_id"), Class->GetPathName() + TEXT("#ModifierDefault"));
    Row->SetStringField(TEXT("class_path"), Class->GetPathName());
    Row->SetStringField(TEXT("modifier_kind"), Kind);
    Row->SetStringField(TEXT("area_class"), NavigationObjectPath(CDO, TEXT("AreaClass")));
    Row->SetStringField(TEXT("area_class_to_replace"), NavigationObjectPath(CDO, TEXT("AreaClassToReplace")));
    Row->SetBoolField(TEXT("include_agent_height"), NavigationBoolValue(CDO, TEXT("bIncludeAgentHeight")));
    if (!GNavigationWriters.ModifierDefaults.Write(Row)) return false;
    ++GNavigationCounts.ModifierDefaults;
    return true;
}

static bool NavigationWriteInvoker(UClass* Class)
{
    if (!Class) return false;
    UObject* CDO = Class->GetDefaultObject();
    if (!CDO) return false;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("invoker_id"), Class->GetPathName() + TEXT("#InvokerDefault"));
    Row->SetStringField(TEXT("class_path"), Class->GetPathName());
    Row->SetStringField(TEXT("tile_generation_radius"), NavigationExportValue(CDO, TEXT("TileGenerationRadius")));
    Row->SetStringField(TEXT("tile_removal_radius"), NavigationExportValue(CDO, TEXT("TileRemovalRadius")));
    Row->SetStringField(TEXT("invoker_priority"), NavigationExportValue(CDO, TEXT("InvokerPriority")));
    Row->SetArrayField(TEXT("supported_agents"), NavigationSupportedAgents(CDO, TEXT("SupportedAgents")));
    if (!GNavigationWriters.InvokerDefaults.Write(Row)) return false;
    ++GNavigationCounts.InvokerDefaults;
    return true;
}

static bool NavigationWriteBounds(UClass* Class)
{
    if (!Class) return false;
    UObject* CDO = Class->GetDefaultObject();
    if (!CDO) return false;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("bounds_id"), Class->GetPathName() + TEXT("#BoundsDefault"));
    Row->SetStringField(TEXT("class_path"), Class->GetPathName());
    Row->SetArrayField(TEXT("supported_agents"), NavigationSupportedAgents(CDO, TEXT("SupportedAgents")));
    if (!GNavigationWriters.BoundsDefaults.Write(Row)) return false;
    ++GNavigationCounts.BoundsDefaults;
    return true;
}

static FString NavigationDirectOrConfigExport(
    UObject* CDO,
    const FName DirectProperty,
    const FName ConfigProperty)
{
    FString Value = NavigationExportValue(CDO, DirectProperty);
    if (Value.IsEmpty() && ConfigProperty != NAME_None)
        Value = NavigationNestedExport(CDO, TEXT("NavDataConfig"), ConfigProperty);
    return Value;
}

static bool NavigationWriteRecast(UClass* Class)
{
    if (!Class) return false;
    UObject* CDO = Class->GetDefaultObject();
    if (!CDO) return false;
    if (Class->HasAnyClassFlags(CLASS_Config)) CDO->LoadConfig();

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("recast_id"), Class->GetPathName() + TEXT("#RecastDefaults"));
    Row->SetStringField(TEXT("class_path"), Class->GetPathName());
    Row->SetStringField(TEXT("runtime_generation"), NavigationExportValue(CDO, TEXT("RuntimeGeneration")));
    Row->SetStringField(TEXT("cell_size"), NavigationExportValue(CDO, TEXT("CellSize")));
    Row->SetStringField(TEXT("cell_height"), NavigationExportValue(CDO, TEXT("CellHeight")));
    Row->SetStringField(TEXT("tile_size_uu"), NavigationExportValue(CDO, TEXT("TileSizeUU")));
    Row->SetStringField(TEXT("agent_radius"), NavigationDirectOrConfigExport(CDO, TEXT("AgentRadius"), TEXT("AgentRadius")));
    Row->SetStringField(TEXT("agent_height"), NavigationDirectOrConfigExport(CDO, TEXT("AgentHeight"), TEXT("AgentHeight")));
    Row->SetStringField(TEXT("agent_max_step_height"), NavigationDirectOrConfigExport(CDO, TEXT("AgentMaxStepHeight"), TEXT("AgentStepHeight")));
    Row->SetStringField(TEXT("nav_data_config"), NavigationExportValue(CDO, TEXT("NavDataConfig")));
    Row->SetStringField(TEXT("jump_down_area_class"),
        NavigationNestedObjectPath(CDO, TEXT("NavLinkJumpDownConfig"), TEXT("DownDirectionAreaClass")));
    Row->SetStringField(TEXT("jump_up_area_class"),
        NavigationNestedObjectPath(CDO, TEXT("NavLinkJumpDownConfig"), TEXT("UpDirectionAreaClass")));
    if (!GNavigationWriters.RecastDefaults.Write(Row)) return false;
    ++GNavigationCounts.RecastDefaults;
    return true;
}

static bool ScanNavigationProjectModel(FString& OutError)
{
    FModuleManager::Get().LoadModule(TEXT("NavigationSystem"));
    FModuleManager::Get().LoadModule(TEXT("AIModule"));

    TMap<FString, UClass*> Classes;
    for (const TCHAR* Path : NavigationExpectedClassPaths)
    {
        if (UClass* Class = NavigationLoadClass(Path))
            Classes.Add(Class->GetPathName(), Class);
        else
            ++GNavigationCounts.MissingExpectedClasses;
    }

    UClass* NavAreaBase = Classes.FindRef(TEXT("/Script/NavigationSystem.NavArea"));
    if (!NavAreaBase)
    {
        OutError = TEXT("could not load /Script/NavigationSystem.NavArea");
        return false;
    }
    if (!NavigationWriteAreas(NavAreaBase))
    {
        OutError = TEXT("failed writing Navigation area definitions");
        return false;
    }

    UClass* NavigationSystem = Classes.FindRef(TEXT("/Script/NavigationSystem.NavigationSystemV1"));
    UClass* NavigationSystemConfig = Classes.FindRef(TEXT("/Script/Engine.NavigationSystemConfig"));
    if (!NavigationWriteSystem(NavigationSystem, TEXT("navigation_system"), true) ||
        !NavigationWriteSystem(NavigationSystemConfig, TEXT("navigation_system_config"), false))
    {
        OutError = TEXT("failed writing Navigation system/agent defaults");
        return false;
    }

    UClass* NavLinkProxy = Classes.FindRef(TEXT("/Script/AIModule.NavLinkProxy"));
    UClass* NavLinkCustom = Classes.FindRef(TEXT("/Script/NavigationSystem.NavLinkCustomComponent"));
    if (!NavigationWriteSimpleLinks(NavLinkProxy) || !NavigationWriteSmartLink(NavLinkCustom, NavLinkProxy))
    {
        OutError = TEXT("failed writing Navigation link defaults");
        return false;
    }

    if (!NavigationWriteModifier(Classes.FindRef(TEXT("/Script/NavigationSystem.NavModifierComponent")), TEXT("component")) ||
        !NavigationWriteModifier(Classes.FindRef(TEXT("/Script/NavigationSystem.NavModifierVolume")), TEXT("volume")))
    {
        OutError = TEXT("failed writing Navigation modifier defaults");
        return false;
    }

    if (!NavigationWriteInvoker(Classes.FindRef(TEXT("/Script/NavigationSystem.NavigationInvokerComponent"))) ||
        !NavigationWriteBounds(Classes.FindRef(TEXT("/Script/NavigationSystem.NavMeshBoundsVolume"))) ||
        !NavigationWriteRecast(Classes.FindRef(TEXT("/Script/NavigationSystem.RecastNavMesh"))))
    {
        OutError = TEXT("failed writing Navigation invoker/bounds/Recast defaults");
        return false;
    }

    if (GNavigationCounts.MissingExpectedClasses != 0)
    {
        OutError = FString::Printf(
            TEXT("missing %lld expected UE 5.8 Navigation classes"),
            GNavigationCounts.MissingExpectedClasses);
        return false;
    }
    return true;
}
