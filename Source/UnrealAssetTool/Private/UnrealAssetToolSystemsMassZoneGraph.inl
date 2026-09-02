struct FMassZoneGraphCounts
{
    int64 EntityConfigs = 0;
    int64 EntityTraits = 0;
    int64 Spawners = 0;
    int64 SpawnerEntityTypes = 0;
    int64 SpawnerGenerators = 0;
    int64 SpawnGeneratorAssets = 0;
    int64 AgentComponents = 0;
    int64 ZoneShapes = 0;
    int64 ZoneShapePoints = 0;
};

struct FMassZoneGraphWriters
{
    FJsonlWriter EntityConfigs;
    FJsonlWriter EntityTraits;
    FJsonlWriter Spawners;
    FJsonlWriter SpawnerEntityTypes;
    FJsonlWriter SpawnerGenerators;
    FJsonlWriter SpawnGeneratorAssets;
    FJsonlWriter AgentComponents;
    FJsonlWriter ZoneShapes;
    FJsonlWriter ZoneShapePoints;

    bool Open(const FString& OutputDir)
    {
        return EntityConfigs.Open(FPaths::Combine(OutputDir, TEXT("mass_entity_configs.jsonl"))) &&
            EntityTraits.Open(FPaths::Combine(OutputDir, TEXT("mass_entity_traits.jsonl"))) &&
            Spawners.Open(FPaths::Combine(OutputDir, TEXT("mass_spawners.jsonl"))) &&
            SpawnerEntityTypes.Open(FPaths::Combine(OutputDir, TEXT("mass_spawner_entity_types.jsonl"))) &&
            SpawnerGenerators.Open(FPaths::Combine(OutputDir, TEXT("mass_spawner_generators.jsonl"))) &&
            SpawnGeneratorAssets.Open(FPaths::Combine(OutputDir, TEXT("mass_spawn_generator_assets.jsonl"))) &&
            AgentComponents.Open(FPaths::Combine(OutputDir, TEXT("mass_agent_components.jsonl"))) &&
            ZoneShapes.Open(FPaths::Combine(OutputDir, TEXT("zonegraph_shapes.jsonl"))) &&
            ZoneShapePoints.Open(FPaths::Combine(OutputDir, TEXT("zonegraph_shape_points.jsonl")));
    }
};

static FMassZoneGraphCounts GMassZoneGraphCounts;
static FMassZoneGraphWriters GMassZoneGraphWriters;

struct FReflectedObjectRef
{
    FString Path;
    FString ClassPath;
    UObject* Object = nullptr;
};

static bool ClassInheritsAnyName(const UClass* Class, std::initializer_list<const TCHAR*> BaseNames)
{
    for (const TCHAR* BaseName : BaseNames)
    {
        if (ClassInheritsName(Class, BaseName))
        {
            return true;
        }
    }
    return false;
}

static bool IsMassEntityConfigClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("MassEntityConfigAsset"));
}

static bool IsMassSpawnerClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("MassSpawner"));
}

static bool IsMassSpawnGeneratorClass(const UClass* Class)
{
    return ClassInheritsAnyName(
        Class,
        {TEXT("MassEntitySpawnDataGeneratorBase"), TEXT("MassEntityZoneGraphSpawnPointsGenerator")});
}

static bool IsMassAgentComponentClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("MassAgentComponent"));
}

static bool IsZoneShapeClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("ZoneShape"));
}

static bool IsZoneShapeComponentClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("ZoneShapeComponent"));
}

static const FStructProperty* FindStructPropertyByTypeName(
    const UStruct* OwnerStruct,
    const TCHAR* StructName)
{
    if (!OwnerStruct)
    {
        return nullptr;
    }
    for (TFieldIterator<FProperty> It(OwnerStruct); It; ++It)
    {
        const FStructProperty* StructProperty = CastField<FStructProperty>(*It);
        if (StructProperty && StructProperty->Struct &&
            StructProperty->Struct->GetName().Equals(StructName, ESearchCase::CaseSensitive))
        {
            return StructProperty;
        }
    }
    return nullptr;
}

static bool GetStructValueByTypeName(
    UObject* Owner,
    const TCHAR* StructName,
    const FStructProperty*& OutProperty,
    const void*& OutValue)
{
    OutProperty = nullptr;
    OutValue = nullptr;
    if (!Owner)
    {
        return false;
    }
    const FStructProperty* Property = FindStructPropertyByTypeName(Owner->GetClass(), StructName);
    if (!Property)
    {
        return false;
    }
    const void* Value = Property->ContainerPtrToValuePtr<void>(Owner);
    if (!Value)
    {
        return false;
    }
    OutProperty = Property;
    OutValue = Value;
    return true;
}

static FReflectedObjectRef ReadObjectReference(const FProperty* Property, const void* ValuePtr)
{
    FReflectedObjectRef Result;
    if (!Property || !ValuePtr)
    {
        return Result;
    }

    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* SoftPtr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (SoftPtr && !SoftPtr->IsNull())
        {
            Result.Path = SoftPtr->ToSoftObjectPath().ToString();
            Result.Object = SoftPtr->Get();
            if (Result.Object)
            {
                Result.ClassPath = Result.Object->GetClass()->GetPathName();
            }
        }
        return Result;
    }

    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        Result.Object = ObjectProperty->GetObjectPropertyValue(ValuePtr);
        if (Result.Object)
        {
            Result.Path = Result.Object->GetPathName();
            Result.ClassPath = Result.Object->GetClass()->GetPathName();
        }
    }
    return Result;
}

static FReflectedObjectRef ReadObjectField(
    const UStruct* Struct,
    const void* StructValue,
    const FName FieldName)
{
    if (!Struct || !StructValue)
    {
        return FReflectedObjectRef();
    }
    const FProperty* Property = Struct->FindPropertyByName(FieldName);
    if (!Property)
    {
        return FReflectedObjectRef();
    }
    return ReadObjectReference(Property, Property->ContainerPtrToValuePtr<void>(StructValue));
}

static FString ExportStructField(
    const UStruct* Struct,
    const void* StructValue,
    UObject* Owner,
    std::initializer_list<const TCHAR*> FieldNames)
{
    return ExportFirstField(Struct, StructValue, Owner, FieldNames);
}

static FString ExportArrayElement(
    const FArrayProperty* ArrayProperty,
    const void* ElementValue,
    UObject* Owner,
    bool& bTruncated)
{
    return ArrayProperty && ArrayProperty->Inner
        ? ExportProperty(ArrayProperty->Inner, ElementValue, Owner, bTruncated)
        : FString();
}

static bool WriteMassEntityConfig(
    UObject* ConfigAsset,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!ConfigAsset || !IsMassEntityConfigClass(ConfigAsset->GetClass()))
    {
        return true;
    }

    const FStructProperty* ConfigProperty = nullptr;
    const void* ConfigValue = nullptr;
    if (!GetStructValueByTypeName(ConfigAsset, TEXT("MassEntityConfig"), ConfigProperty, ConfigValue))
    {
        return true;
    }

    const UStruct* ConfigStruct = ConfigProperty->Struct;
    const FReflectedObjectRef Parent = ReadObjectField(ConfigStruct, ConfigValue, FName(TEXT("Parent")));
    const FString ConfigGuid = ExportStructField(
        ConfigStruct, ConfigValue, ConfigAsset, {TEXT("ConfigGuid")});

    int32 TraitCount = 0;
    const FArrayProperty* TraitsProperty =
        CastField<FArrayProperty>(ConfigStruct->FindPropertyByName(FName(TEXT("Traits"))));
    const void* TraitsValue = TraitsProperty
        ? TraitsProperty->ContainerPtrToValuePtr<void>(ConfigValue)
        : nullptr;
    if (TraitsProperty && TraitsValue)
    {
        FScriptArrayHelper Helper(TraitsProperty, TraitsValue);
        TraitCount = Helper.Num();
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            FReflectedObjectRef Trait = ReadObjectReference(TraitsProperty->Inner, Helper.GetRawPtr(Index));
            TSharedRef<FJsonObject> TraitRow = MakeShared<FJsonObject>();
            TraitRow->SetStringField(TEXT("config_path"), ConfigAsset->GetPathName());
            TraitRow->SetNumberField(TEXT("trait_index"), Index);
            TraitRow->SetStringField(TEXT("trait_path"), Trait.Path);
            TraitRow->SetStringField(TEXT("trait_class"), Trait.ClassPath);
            if (!GMassZoneGraphWriters.EntityTraits.Write(TraitRow))
            {
                return false;
            }
            ++GMassZoneGraphCounts.EntityTraits;
            if (Trait.Object && !WriteObjectState(
                    Trait.Object,
                    ConfigAsset->GetPathName(),
                    TEXT("mass_entity_trait"),
                    Writers,
                    Counts,
                    SeenStateOwners))
            {
                return false;
            }
        }
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("config_path"), ConfigAsset->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("class_path"), ConfigAsset->GetClass()->GetPathName());
    Row->SetStringField(TEXT("config_property"), ConfigProperty->GetName());
    Row->SetStringField(TEXT("config_guid"), ConfigGuid);
    Row->SetStringField(TEXT("parent_config_path"), Parent.Path);
    Row->SetStringField(TEXT("parent_config_class"), Parent.ClassPath);
    Row->SetNumberField(TEXT("trait_count"), TraitCount);
    if (!GMassZoneGraphWriters.EntityConfigs.Write(Row))
    {
        return false;
    }
    ++GMassZoneGraphCounts.EntityConfigs;

    return WriteObjectState(
        ConfigAsset,
        ConfigAsset->GetPathName(),
        TEXT("mass_entity_config"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool WriteMassSpawnerArrayRows(
    const FString& BlueprintPath,
    UObject* CDO,
    const FName PropertyName,
    bool bGenerators,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners,
    int32& OutCount)
{
    OutCount = 0;
    if (!CDO)
    {
        return true;
    }

    const FArrayProperty* ArrayProperty =
        CastField<FArrayProperty>(CDO->GetClass()->FindPropertyByName(PropertyName));
    if (!ArrayProperty)
    {
        return true;
    }
    const FStructProperty* InnerStruct = CastField<FStructProperty>(ArrayProperty->Inner);
    if (!InnerStruct || !InnerStruct->Struct)
    {
        return true;
    }
    const void* ArrayValue = ArrayProperty->ContainerPtrToValuePtr<void>(CDO);
    if (!ArrayValue)
    {
        return true;
    }

    FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
    OutCount = Helper.Num();
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Element = Helper.GetRawPtr(Index);
        bool bTruncated = false;
        const FString RawValue = ExportArrayElement(ArrayProperty, Element, CDO, bTruncated);
        const FString Proportion = ExportStructField(
            InnerStruct->Struct, Element, CDO, {TEXT("Proportion")});

        if (bGenerators)
        {
            const FReflectedObjectRef Generator = ReadObjectField(
                InnerStruct->Struct, Element, FName(TEXT("GeneratorInstance")));
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("spawner_path"), BlueprintPath);
            Row->SetNumberField(TEXT("generator_index"), Index);
            Row->SetStringField(TEXT("generator_path"), Generator.Path);
            Row->SetStringField(TEXT("generator_class"), Generator.ClassPath);
            Row->SetStringField(TEXT("generator_asset_path"), BlueprintPathForGeneratedClass(Generator.ClassPath));
            Row->SetStringField(TEXT("proportion"), Proportion);
            Row->SetStringField(TEXT("raw_value"), RawValue);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!GMassZoneGraphWriters.SpawnerGenerators.Write(Row))
            {
                return false;
            }
            ++GMassZoneGraphCounts.SpawnerGenerators;
            if (Generator.Object && !WriteObjectState(
                    Generator.Object,
                    BlueprintPath,
                    TEXT("mass_spawn_generator_instance"),
                    Writers,
                    Counts,
                    SeenStateOwners))
            {
                return false;
            }
        }
        else
        {
            const FReflectedObjectRef EntityConfig = ReadObjectField(
                InnerStruct->Struct, Element, FName(TEXT("EntityConfig")));
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("spawner_path"), BlueprintPath);
            Row->SetNumberField(TEXT("entity_type_index"), Index);
            Row->SetStringField(TEXT("entity_config_path"), EntityConfig.Path);
            Row->SetStringField(TEXT("entity_config_class"), EntityConfig.ClassPath);
            Row->SetStringField(TEXT("proportion"), Proportion);
            Row->SetStringField(TEXT("raw_value"), RawValue);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!GMassZoneGraphWriters.SpawnerEntityTypes.Write(Row))
            {
                return false;
            }
            ++GMassZoneGraphCounts.SpawnerEntityTypes;
        }
    }
    return true;
}

static bool WriteMassSpawnerBlueprint(
    UBlueprint* Blueprint,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Blueprint || !Blueprint->GeneratedClass || !IsMassSpawnerClass(Blueprint->GeneratedClass))
    {
        return true;
    }

    const FString BlueprintPath = Asset.GetSoftObjectPath().ToString();
    UObject* CDO = Blueprint->GeneratedClass->GetDefaultObject(false);
    int32 EntityTypeCount = 0;
    int32 GeneratorCount = 0;
    if (!WriteMassSpawnerArrayRows(
            BlueprintPath,
            CDO,
            FName(TEXT("EntityTypes")),
            false,
            Writers,
            Counts,
            SeenStateOwners,
            EntityTypeCount) ||
        !WriteMassSpawnerArrayRows(
            BlueprintPath,
            CDO,
            FName(TEXT("SpawnDataGenerators")),
            true,
            Writers,
            Counts,
            SeenStateOwners,
            GeneratorCount))
    {
        return false;
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("spawner_path"), BlueprintPath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("generated_class"), Blueprint->GeneratedClass->GetPathName());
    Row->SetStringField(TEXT("cdo_path"), CDO ? CDO->GetPathName() : FString());
    Row->SetNumberField(TEXT("entity_type_count"), EntityTypeCount);
    Row->SetNumberField(TEXT("spawn_generator_count"), GeneratorCount);
    Row->SetStringField(TEXT("count"), CDO ? ExportFirstField(CDO, {TEXT("Count")}) : FString());
    Row->SetStringField(
        TEXT("auto_spawn_on_begin_play"),
        CDO ? ExportFirstField(CDO, {TEXT("bAutoSpawnOnBeginPlay")}) : FString());
    if (!GMassZoneGraphWriters.Spawners.Write(Row))
    {
        return false;
    }
    ++GMassZoneGraphCounts.Spawners;

    return !CDO || WriteObjectState(
        CDO,
        BlueprintPath,
        TEXT("mass_spawner"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool WriteMassSpawnGeneratorBlueprint(
    UBlueprint* Blueprint,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Blueprint || !Blueprint->GeneratedClass || !IsMassSpawnGeneratorClass(Blueprint->GeneratedClass))
    {
        return true;
    }

    const FString BlueprintPath = Asset.GetSoftObjectPath().ToString();
    UObject* CDO = Blueprint->GeneratedClass->GetDefaultObject(false);
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("generator_asset_path"), BlueprintPath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("generated_class"), Blueprint->GeneratedClass->GetPathName());
    Row->SetStringField(
        TEXT("parent_class"),
        Blueprint->GeneratedClass->GetSuperClass()
            ? Blueprint->GeneratedClass->GetSuperClass()->GetPathName()
            : FString());
    Row->SetStringField(TEXT("cdo_path"), CDO ? CDO->GetPathName() : FString());
    Row->SetBoolField(
        TEXT("zonegraph_generator"),
        ClassInheritsName(Blueprint->GeneratedClass, TEXT("MassEntityZoneGraphSpawnPointsGenerator")));
    if (!GMassZoneGraphWriters.SpawnGeneratorAssets.Write(Row))
    {
        return false;
    }
    ++GMassZoneGraphCounts.SpawnGeneratorAssets;

    return !CDO || WriteObjectState(
        CDO,
        BlueprintPath,
        TEXT("mass_spawn_generator_asset"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool WriteMassAgentComponent(
    const FString& BlueprintPath,
    const FString& ComponentName,
    UObject* Component,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Component || !IsMassAgentComponentClass(Component->GetClass()))
    {
        return true;
    }

    const FStructProperty* EntityConfigProperty = nullptr;
    const void* EntityConfigValue = nullptr;
    FReflectedObjectRef Parent;
    FString ConfigGuid;
    FString RawConfig;
    bool bTruncated = false;
    if (GetStructValueByTypeName(
            Component,
            TEXT("MassEntityConfig"),
            EntityConfigProperty,
            EntityConfigValue))
    {
        Parent = ReadObjectField(EntityConfigProperty->Struct, EntityConfigValue, FName(TEXT("Parent")));
        ConfigGuid = ExportStructField(
            EntityConfigProperty->Struct, EntityConfigValue, Component, {TEXT("ConfigGuid")});
        RawConfig = ExportProperty(
            EntityConfigProperty,
            EntityConfigValue,
            Component,
            bTruncated);
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("component_path"), Component->GetPathName());
    Row->SetStringField(TEXT("blueprint_path"), BlueprintPath);
    Row->SetStringField(TEXT("component_name"), ComponentName);
    Row->SetStringField(TEXT("component_class"), Component->GetClass()->GetPathName());
    Row->SetStringField(TEXT("entity_config_parent_path"), Parent.Path);
    Row->SetStringField(TEXT("entity_config_parent_class"), Parent.ClassPath);
    Row->SetStringField(TEXT("config_guid"), ConfigGuid);
    Row->SetStringField(TEXT("raw_entity_config"), RawConfig);
    Row->SetBoolField(TEXT("truncated"), bTruncated);
    if (!GMassZoneGraphWriters.AgentComponents.Write(Row))
    {
        return false;
    }
    ++GMassZoneGraphCounts.AgentComponents;

    return WriteObjectState(
        Component,
        BlueprintPath,
        TEXT("mass_agent_component"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool ScanMassAgentComponents(
    UBlueprint* Blueprint,
    const FString& BlueprintPath,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Blueprint || !Blueprint->GeneratedClass)
    {
        return true;
    }

    TMap<FString, UObject*> Components;
    TMap<FString, FString> Names;
    if (Blueprint->SimpleConstructionScript)
    {
        for (USCS_Node* Node : Blueprint->SimpleConstructionScript->GetAllNodes())
        {
            if (!Node || !Node->ComponentTemplate ||
                !IsMassAgentComponentClass(Node->ComponentTemplate->GetClass()))
            {
                continue;
            }
            const FString Path = Node->ComponentTemplate->GetPathName();
            Components.FindOrAdd(Path) = Node->ComponentTemplate;
            Names.FindOrAdd(Path) = Node->GetVariableName().ToString();
        }
    }

    if (UObject* CDO = Blueprint->GeneratedClass->GetDefaultObject(false))
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
            if (UActorComponent* ActorComponent = Cast<UActorComponent>(Object))
            {
                if (IsMassAgentComponentClass(ActorComponent->GetClass()))
                {
                    const FString Path = ActorComponent->GetPathName();
                    Components.FindOrAdd(Path) = ActorComponent;
                    Names.FindOrAdd(Path) = ActorComponent->GetName();
                }
            }
        }
    }

    TArray<FString> Paths;
    Components.GetKeys(Paths);
    Paths.Sort();
    for (const FString& Path : Paths)
    {
        if (!WriteMassAgentComponent(
                BlueprintPath,
                Names.FindRef(Path),
                Components.FindRef(Path),
                Writers,
                Counts,
                SeenStateOwners))
        {
            return false;
        }
    }
    return true;
}

static UObject* FindZoneShapeComponent(UObject* Shape)
{
    if (!Shape)
    {
        return nullptr;
    }
    for (const TCHAR* Name : {TEXT("ShapeComp"), TEXT("ShapeComponent")})
    {
        if (UObject* Candidate = GetObjectField(Shape, FName(Name)))
        {
            if (IsZoneShapeComponentClass(Candidate->GetClass()))
            {
                return Candidate;
            }
        }
    }
    TArray<UObject*> Nested;
    GatherNestedObjects(Shape, Nested);
    for (UObject* Candidate : Nested)
    {
        if (Candidate && IsZoneShapeComponentClass(Candidate->GetClass()))
        {
            return Candidate;
        }
    }
    return nullptr;
}

static bool WriteZoneShape(
    UObject* Shape,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Shape || !IsZoneShapeClass(Shape->GetClass()))
    {
        return true;
    }
    UObject* Component = FindZoneShapeComponent(Shape);
    if (!Component)
    {
        return true;
    }

    const FArrayProperty* PointsProperty =
        CastField<FArrayProperty>(Component->GetClass()->FindPropertyByName(FName(TEXT("Points"))));
    const FStructProperty* PointStruct = PointsProperty
        ? CastField<FStructProperty>(PointsProperty->Inner)
        : nullptr;
    const void* PointsValue = PointsProperty
        ? PointsProperty->ContainerPtrToValuePtr<void>(Component)
        : nullptr;
    int32 PointCount = 0;
    if (PointsProperty && PointStruct && PointStruct->Struct && PointsValue)
    {
        FScriptArrayHelper Helper(PointsProperty, PointsValue);
        PointCount = Helper.Num();
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Point = Helper.GetRawPtr(Index);
            bool bTruncated = false;
            const FString RawValue = ExportArrayElement(PointsProperty, Point, Component, bTruncated);
            TSharedRef<FJsonObject> PointRow = MakeShared<FJsonObject>();
            PointRow->SetStringField(TEXT("shape_path"), Shape->GetPathName());
            PointRow->SetNumberField(TEXT("point_index"), Index);
            PointRow->SetStringField(
                TEXT("position"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("Position")}));
            PointRow->SetStringField(
                TEXT("rotation"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("Rotation")}));
            PointRow->SetStringField(
                TEXT("tangent_length"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("TangentLength")}));
            PointRow->SetStringField(
                TEXT("point_type"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("Type"), TEXT("PointType")}));
            PointRow->SetStringField(
                TEXT("lane_profile"),
                ExportStructField(PointStruct->Struct, Point, Component, {TEXT("LaneProfile")}));
            PointRow->SetStringField(
                TEXT("lane_connection_restrictions"),
                ExportStructField(
                    PointStruct->Struct,
                    Point,
                    Component,
                    {TEXT("LaneConnectionRestrictions")}));
            PointRow->SetStringField(TEXT("raw_value"), RawValue);
            PointRow->SetBoolField(TEXT("truncated"), bTruncated);
            if (!GMassZoneGraphWriters.ZoneShapePoints.Write(PointRow))
            {
                return false;
            }
            ++GMassZoneGraphCounts.ZoneShapePoints;
        }
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("shape_path"), Shape->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("class_path"), Shape->GetClass()->GetPathName());
    Row->SetStringField(TEXT("component_path"), Component->GetPathName());
    Row->SetStringField(TEXT("component_class"), Component->GetClass()->GetPathName());
    Row->SetNumberField(TEXT("point_count"), PointCount);
    Row->SetStringField(TEXT("shape_type"), ExportFirstField(Component, {TEXT("ShapeType")}));
    Row->SetStringField(TEXT("lane_profile"), ExportFirstField(Component, {TEXT("LaneProfile")}));
    Row->SetStringField(TEXT("tags"), ExportFirstField(Component, {TEXT("Tags")}));
    Row->SetStringField(
        TEXT("reverse_lane_profile"),
        ExportFirstField(Component, {TEXT("bReverseLaneProfile")}));
    Row->SetStringField(
        TEXT("polygon_routing_type"),
        ExportFirstField(Component, {TEXT("PolygonRoutingType")}));
    Row->SetStringField(
        TEXT("relative_location"),
        ExportFirstField(Component, {TEXT("RelativeLocation")}));
    Row->SetStringField(
        TEXT("relative_rotation"),
        ExportFirstField(Component, {TEXT("RelativeRotation")}));
    if (!GMassZoneGraphWriters.ZoneShapes.Write(Row))
    {
        return false;
    }
    ++GMassZoneGraphCounts.ZoneShapes;

    return WriteObjectState(
        Component,
        Shape->GetPathName(),
        TEXT("zonegraph_shape_component"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool AssetInSystemsScope(
    const FAssetData& Asset,
    const FString& ProjectDir,
    bool bIncludeEngine,
    bool bIncludeSelf,
    const FString& ToolPluginDir)
{
    FString PackageFilename;
    const bool bHasDiskPackage = FPackageName::DoesPackageExist(
        Asset.PackageName.ToString(),
        &PackageFilename,
        false);
    if (!bIncludeSelf && bHasDiskPackage && !ToolPluginDir.IsEmpty() &&
        IsInsideDirectory(PackageFilename, ToolPluginDir))
    {
        return false;
    }
    return bIncludeEngine || (bHasDiskPackage && IsInsideDirectory(PackageFilename, ProjectDir));
}

static bool AssetLooksLikeZoneShape(const FAssetData& Asset)
{
    if (Asset.AssetClassPath.ToString() == TEXT("/Script/ZoneGraph.ZoneShape"))
    {
        return true;
    }
    FString ActorMetaDataClass;
    return Asset.GetTagValue(FName(TEXT("ActorMetaDataClass")), ActorMetaDataClass) &&
        ActorMetaDataClass == TEXT("/Script/ZoneGraph.ZoneShape");
}

static bool ScanMassZoneGraphProjectModel(
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
        if (!AssetInSystemsScope(
                Asset,
                ProjectDir,
                bIncludeEngine,
                bIncludeSelf,
                ToolPluginDir))
        {
            continue;
        }

        const FString ClassPath = Asset.AssetClassPath.ToString();
        if (ClassPath == TEXT("/Script/MassSpawner.MassEntityConfigAsset"))
        {
            UObject* Object = Asset.GetAsset();
            if (Object && !WriteMassEntityConfig(
                    Object,
                    Asset,
                    Writers,
                    Counts,
                    SeenStateOwners))
            {
                OutError = TEXT("failed while scanning Mass entity config ") +
                    Asset.GetSoftObjectPath().ToString();
                return false;
            }
            continue;
        }

        if (AssetLooksLikeZoneShape(Asset))
        {
            UObject* Object = Asset.GetAsset();
            if (Object && !WriteZoneShape(
                    Object,
                    Asset,
                    Writers,
                    Counts,
                    SeenStateOwners))
            {
                OutError = TEXT("failed while scanning ZoneShape ") +
                    Asset.GetSoftObjectPath().ToString();
                return false;
            }
            continue;
        }

        if (Asset.AssetClassPath != UBlueprint::StaticClass()->GetClassPathName())
        {
            continue;
        }

        UBlueprint* Blueprint = Cast<UBlueprint>(Asset.GetAsset());
        if (!Blueprint || !Blueprint->GeneratedClass)
        {
            continue;
        }
        const FString BlueprintPath = Asset.GetSoftObjectPath().ToString();
        if (!WriteMassSpawnerBlueprint(
                Blueprint,
                Asset,
                Writers,
                Counts,
                SeenStateOwners) ||
            !WriteMassSpawnGeneratorBlueprint(
                Blueprint,
                Asset,
                Writers,
                Counts,
                SeenStateOwners) ||
            !ScanMassAgentComponents(
                Blueprint,
                BlueprintPath,
                Writers,
                Counts,
                SeenStateOwners))
        {
            OutError = TEXT("failed while scanning Mass Blueprint ") + BlueprintPath;
            return false;
        }
    }
    return true;
}
