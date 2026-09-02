struct FAIPerceptionCounts
{
    int64 Components = 0;
    int64 SenseConfigs = 0;
    int64 StimuliSources = 0;
    int64 RegisteredSenses = 0;
    int64 Properties = 0;
    int64 TruncatedProperties = 0;
    int64 PropertyDepthLimitHits = 0;
    int64 PropertyRowLimitHits = 0;
    int64 ContainerElementLimitHits = 0;
};

struct FAIPerceptionWriters
{
    FJsonlWriter Components;
    FJsonlWriter SenseConfigs;
    FJsonlWriter StimuliSources;
    FJsonlWriter RegisteredSenses;
    FJsonlWriter Properties;

    bool Open(const FString& OutputDir)
    {
        return Components.Open(FPaths::Combine(OutputDir, TEXT("ai_perception_components.jsonl"))) &&
            SenseConfigs.Open(FPaths::Combine(OutputDir, TEXT("ai_perception_sense_configs.jsonl"))) &&
            StimuliSources.Open(FPaths::Combine(OutputDir, TEXT("ai_perception_stimuli_sources.jsonl"))) &&
            RegisteredSenses.Open(FPaths::Combine(OutputDir, TEXT("ai_perception_registered_senses.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("ai_perception_properties.jsonl")));
    }
};

static FAIPerceptionCounts GAIPerceptionCounts;
static FAIPerceptionWriters GAIPerceptionWriters;

static constexpr int32 AIPerceptionMaxPropertyDepth = 16;
static constexpr int32 AIPerceptionMaxElementsPerContainer = 4096;
static constexpr int32 AIPerceptionMaxPropertyRowsPerObject = 65536;
static constexpr int32 AIPerceptionMaxObjectsPerBlueprint = 4096;

static bool AIPerceptionBlueprintCandidate(const FAssetData& Asset)
{
    const FString ClassPath = Asset.AssetClassPath.ToString();
    return ClassPath.Contains(TEXT("Blueprint"), ESearchCase::IgnoreCase);
}

static bool AIPerceptionTryBoolField(UObject* Object, const FName FieldName, bool& OutValue)
{
    if (!Object)
    {
        return false;
    }
    const FBoolProperty* Property = CastField<FBoolProperty>(Object->GetClass()->FindPropertyByName(FieldName));
    if (!Property)
    {
        return false;
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    if (!ValuePtr)
    {
        return false;
    }
    OutValue = Property->GetPropertyValue(ValuePtr);
    return true;
}

static bool AIPerceptionTryNumberField(UObject* Object, const FName FieldName, double& OutValue)
{
    if (!Object)
    {
        return false;
    }
    const FProperty* Property = Object->GetClass()->FindPropertyByName(FieldName);
    if (!Property)
    {
        return false;
    }
    bool bTruncated = false;
    const FString Text = ExportProperty(
        Property,
        Property->ContainerPtrToValuePtr<void>(Object),
        Object,
        bTruncated);
    if (Text.IsEmpty())
    {
        return false;
    }
    OutValue = FCString::Atod(*Text);
    return true;
}

static void AIPerceptionSetOptionalNumber(
    const TSharedRef<FJsonObject>& Row,
    const TCHAR* FieldName,
    UObject* Object,
    const FName PropertyName)
{
    double Value = 0.0;
    if (AIPerceptionTryNumberField(Object, PropertyName, Value))
    {
        Row->SetNumberField(FieldName, Value);
    }
    else
    {
        Row->SetField(FieldName, MakeShared<FJsonValueNull>());
    }
}

static void AIPerceptionSetOptionalBool(
    const TSharedRef<FJsonObject>& Row,
    const TCHAR* FieldName,
    const UStruct* Struct,
    const void* Value,
    const FName PropertyName)
{
    if (!Struct || !Value)
    {
        Row->SetField(FieldName, MakeShared<FJsonValueNull>());
        return;
    }
    const FBoolProperty* Property = CastField<FBoolProperty>(Struct->FindPropertyByName(PropertyName));
    const void* ValuePtr = Property ? Property->ContainerPtrToValuePtr<void>(Value) : nullptr;
    if (!Property || !ValuePtr)
    {
        Row->SetField(FieldName, MakeShared<FJsonValueNull>());
        return;
    }
    Row->SetBoolField(FieldName, Property->GetPropertyValue(ValuePtr));
}

struct FAIPerceptionPropertyContext
{
    FString BlueprintPath;
    FString OwnerPath;
    FString OwnerKind;
    UObject* OwnerObject = nullptr;
    UObject* DefaultObject = nullptr;
    int32 PropertyIndex = 0;
    bool bFailed = false;
};

static void AIPerceptionEmitProperty(
    const FProperty* Property,
    const void* ValuePtr,
    const void* DefaultValuePtr,
    const FString& PropertyPath,
    int32 Depth,
    int32 ElementCount,
    FAIPerceptionPropertyContext& Context)
{
    if (!Property || !ValuePtr || Context.bFailed)
    {
        return;
    }
    if (Context.PropertyIndex >= AIPerceptionMaxPropertyRowsPerObject)
    {
        ++GAIPerceptionCounts.PropertyRowLimitHits;
        return;
    }

    bool bTruncated = false;
    const FString Value = ExportProperty(Property, ValuePtr, Context.OwnerObject, bTruncated);
    bool bDefaultTruncated = false;
    const FString DefaultValue = DefaultValuePtr
        ? ExportProperty(Property, DefaultValuePtr, Context.DefaultObject, bDefaultTruncated)
        : FString();
    const bool bDiffers = !DefaultValuePtr || !Property->Identical(ValuePtr, DefaultValuePtr, PPF_None);

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("blueprint_path"), Context.BlueprintPath);
    Row->SetStringField(TEXT("owner_path"), Context.OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetNumberField(TEXT("property_index"), Context.PropertyIndex++);
    Row->SetStringField(
        TEXT("declaring_type"),
        Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString());
    Row->SetStringField(TEXT("property_name"), Property->GetName());
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
    Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
    Row->SetStringField(TEXT("value"), Value);
    Row->SetStringField(TEXT("class_default_value"), DefaultValue);
    Row->SetBoolField(TEXT("class_default_present"), DefaultValuePtr != nullptr);
    Row->SetBoolField(TEXT("differs_from_class_default"), bDiffers);
    Row->SetBoolField(TEXT("truncated"), bTruncated || bDefaultTruncated);
    if (ElementCount >= 0)
    {
        Row->SetNumberField(TEXT("element_count"), ElementCount);
    }
    Row->SetNumberField(TEXT("depth"), Depth);
    if (!GAIPerceptionWriters.Properties.Write(Row))
    {
        Context.bFailed = true;
        return;
    }
    ++GAIPerceptionCounts.Properties;
    if (bTruncated || bDefaultTruncated)
    {
        ++GAIPerceptionCounts.TruncatedProperties;
    }
}

static void AIPerceptionWalkProperty(
    const FProperty* Property,
    const void* ValuePtr,
    const void* DefaultValuePtr,
    const FString& PropertyPath,
    int32 Depth,
    FAIPerceptionPropertyContext& Context)
{
    if (!Property || !ValuePtr || Context.bFailed)
    {
        return;
    }
    if (Depth > AIPerceptionMaxPropertyDepth)
    {
        ++GAIPerceptionCounts.PropertyDepthLimitHits;
        return;
    }
    if (Context.PropertyIndex >= AIPerceptionMaxPropertyRowsPerObject)
    {
        ++GAIPerceptionCounts.PropertyRowLimitHits;
        return;
    }

    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
        AIPerceptionEmitProperty(Property, ValuePtr, DefaultValuePtr, PropertyPath, Depth, Helper.Num(), Context);
        TUniquePtr<FScriptArrayHelper> DefaultHelper;
        if (DefaultValuePtr)
        {
            DefaultHelper = MakeUnique<FScriptArrayHelper>(ArrayProperty, DefaultValuePtr);
        }
        const int32 Limit = FMath::Min(Helper.Num(), AIPerceptionMaxElementsPerContainer);
        if (Helper.Num() > Limit)
        {
            ++GAIPerceptionCounts.ContainerElementLimitHits;
        }
        for (int32 Index = 0; Index < Limit && !Context.bFailed; ++Index)
        {
            const void* ChildDefault =
                DefaultHelper.IsValid() && Index < DefaultHelper->Num()
                    ? DefaultHelper->GetRawPtr(Index)
                    : nullptr;
            AIPerceptionWalkProperty(
                ArrayProperty->Inner,
                Helper.GetRawPtr(Index),
                ChildDefault,
                FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                Depth + 1,
                Context);
        }
        return;
    }

    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, ValuePtr);
        AIPerceptionEmitProperty(Property, ValuePtr, DefaultValuePtr, PropertyPath, Depth, Helper.Num(), Context);
        int32 Emitted = 0;
        for (int32 Index = 0;
             Index < Helper.GetMaxIndex() && Emitted < AIPerceptionMaxElementsPerContainer && !Context.bFailed;
             ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            AIPerceptionWalkProperty(
                SetProperty->ElementProp,
                Helper.GetElementPtr(Index),
                nullptr,
                FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++),
                Depth + 1,
                Context);
        }
        if (Helper.Num() > Emitted)
        {
            ++GAIPerceptionCounts.ContainerElementLimitHits;
        }
        return;
    }

    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, ValuePtr);
        AIPerceptionEmitProperty(Property, ValuePtr, DefaultValuePtr, PropertyPath, Depth, Helper.Num(), Context);
        int32 Emitted = 0;
        for (int32 Index = 0;
             Index < Helper.GetMaxIndex() && Emitted < AIPerceptionMaxElementsPerContainer && !Context.bFailed;
             ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            const FString Base = FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++);
            AIPerceptionWalkProperty(MapProperty->KeyProp, Helper.GetKeyPtr(Index), nullptr, Base + TEXT(".key"), Depth + 1, Context);
            AIPerceptionWalkProperty(MapProperty->ValueProp, Helper.GetValuePtr(Index), nullptr, Base + TEXT(".value"), Depth + 1, Context);
        }
        if (Helper.Num() > Emitted)
        {
            ++GAIPerceptionCounts.ContainerElementLimitHits;
        }
        return;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        AIPerceptionEmitProperty(Property, ValuePtr, DefaultValuePtr, PropertyPath, Depth, -1, Context);
        if (!StructProperty->Struct)
        {
            return;
        }
        for (TFieldIterator<FProperty> It(StructProperty->Struct); It && !Context.bFailed; ++It)
        {
            const FProperty* Inner = *It;
            if (!ShouldInspectProperty(Inner))
            {
                continue;
            }
            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim && !Context.bFailed; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const void* InnerDefault = DefaultValuePtr
                    ? Inner->ContainerPtrToValuePtr<void>(DefaultValuePtr, StaticIndex)
                    : nullptr;
                const FString ChildPath = PropertyPath + TEXT(".") + Inner->GetName() +
                    (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                AIPerceptionWalkProperty(Inner, InnerValue, InnerDefault, ChildPath, Depth + 1, Context);
            }
        }
        return;
    }

    AIPerceptionEmitProperty(Property, ValuePtr, DefaultValuePtr, PropertyPath, Depth, -1, Context);
}

static bool AIPerceptionWriteProperties(
    const FString& BlueprintPath,
    UObject* Object,
    const FString& OwnerKind,
    int32& OutPropertyCount)
{
    OutPropertyCount = 0;
    if (!Object)
    {
        return true;
    }

    FAIPerceptionPropertyContext Context;
    Context.BlueprintPath = BlueprintPath;
    Context.OwnerPath = Object->GetPathName();
    Context.OwnerKind = OwnerKind;
    Context.OwnerObject = Object;
    Context.DefaultObject = Object->GetClass()->GetDefaultObject(false);

    TSet<FString> Seen;
    for (TFieldIterator<FProperty> It(Object->GetClass()); It && !Context.bFailed; ++It)
    {
        FProperty* Property = *It;
        if (!ShouldInspectProperty(Property))
        {
            continue;
        }
        const FString Key =
            (Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString()) +
            TEXT("::") + Property->GetName();
        if (Seen.Contains(Key))
        {
            continue;
        }
        Seen.Add(Key);
        for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim && !Context.bFailed; ++StaticIndex)
        {
            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
            const void* DefaultPtr = Context.DefaultObject
                ? Property->ContainerPtrToValuePtr<void>(Context.DefaultObject, StaticIndex)
                : nullptr;
            const FString Path = Property->GetName() +
                (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
            AIPerceptionWalkProperty(Property, ValuePtr, DefaultPtr, Path, 0, Context);
        }
    }
    OutPropertyCount = Context.PropertyIndex;
    return !Context.bFailed;
}

static bool AIPerceptionWriteSenseConfig(
    const FString& BlueprintPath,
    const FString& ComponentPath,
    int32 ConfigIndex,
    UObject* Config,
    FString& OutError)
{
    if (!Config)
    {
        return true;
    }
    int32 PropertyCount = 0;
    if (!AIPerceptionWriteProperties(BlueprintPath, Config, TEXT("sense_config"), PropertyCount))
    {
        OutError = TEXT("failed writing AI Perception sense config properties: ") + Config->GetPathName();
        return false;
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("blueprint_path"), BlueprintPath);
    Row->SetStringField(TEXT("component_path"), ComponentPath);
    Row->SetNumberField(TEXT("config_index"), ConfigIndex);
    Row->SetStringField(TEXT("config_path"), Config->GetPathName());
    Row->SetStringField(TEXT("config_class"), Config->GetClass()->GetPathName());
    UObject* Implementation = GetObjectField(Config, FName(TEXT("Implementation")));
    Row->SetStringField(TEXT("implementation_class"), Implementation ? Implementation->GetPathName() : FString());
    AIPerceptionSetOptionalNumber(Row, TEXT("max_age"), Config, FName(TEXT("MaxAge")));
    Row->SetStringField(TEXT("detection_by_affiliation"), ExportField(Config, FName(TEXT("DetectionByAffiliation"))));

    const void* AffiliationValue = nullptr;
    const FStructProperty* AffiliationProperty =
        CastField<FStructProperty>(Config->GetClass()->FindPropertyByName(FName(TEXT("DetectionByAffiliation"))));
    if (AffiliationProperty)
    {
        AffiliationValue = AffiliationProperty->ContainerPtrToValuePtr<void>(Config);
    }
    AIPerceptionSetOptionalBool(Row, TEXT("detect_enemies"),
        AffiliationProperty ? AffiliationProperty->Struct : nullptr, AffiliationValue, FName(TEXT("bDetectEnemies")));
    AIPerceptionSetOptionalBool(Row, TEXT("detect_neutrals"),
        AffiliationProperty ? AffiliationProperty->Struct : nullptr, AffiliationValue, FName(TEXT("bDetectNeutrals")));
    AIPerceptionSetOptionalBool(Row, TEXT("detect_friendlies"),
        AffiliationProperty ? AffiliationProperty->Struct : nullptr, AffiliationValue, FName(TEXT("bDetectFriendlies")));

    AIPerceptionSetOptionalNumber(Row, TEXT("hearing_range"), Config, FName(TEXT("HearingRange")));
    AIPerceptionSetOptionalNumber(Row, TEXT("sight_radius"), Config, FName(TEXT("SightRadius")));
    AIPerceptionSetOptionalNumber(Row, TEXT("lose_sight_radius"), Config, FName(TEXT("LoseSightRadius")));
    AIPerceptionSetOptionalNumber(
        Row,
        TEXT("peripheral_vision_angle_degrees"),
        Config,
        FName(TEXT("PeripheralVisionAngleDegrees")));
    Row->SetNumberField(TEXT("property_count"), PropertyCount);
    if (!GAIPerceptionWriters.SenseConfigs.Write(Row))
    {
        OutError = TEXT("failed writing AI Perception sense config row: ") + Config->GetPathName();
        return false;
    }
    ++GAIPerceptionCounts.SenseConfigs;
    return true;
}

static bool AIPerceptionWriteComponent(
    const FString& BlueprintPath,
    UClass* GeneratedClass,
    UObject* Component,
    FString& OutError)
{
    if (!Component)
    {
        return true;
    }

    int32 PropertyCount = 0;
    if (!AIPerceptionWriteProperties(BlueprintPath, Component, TEXT("perception_component_template"), PropertyCount))
    {
        OutError = TEXT("failed writing AI Perception component properties: ") + Component->GetPathName();
        return false;
    }

    int32 ConfigCount = 0;
    const FArrayProperty* ConfigArray =
        CastField<FArrayProperty>(Component->GetClass()->FindPropertyByName(FName(TEXT("SensesConfig"))));
    const FObjectPropertyBase* ConfigInner = ConfigArray
        ? CastField<FObjectPropertyBase>(ConfigArray->Inner)
        : nullptr;
    const void* ConfigArrayValue = ConfigArray ? ConfigArray->ContainerPtrToValuePtr<void>(Component) : nullptr;
    if (ConfigArray && ConfigInner && ConfigArrayValue)
    {
        FScriptArrayHelper Helper(ConfigArray, ConfigArrayValue);
        const int32 Limit = FMath::Min(Helper.Num(), AIPerceptionMaxElementsPerContainer);
        if (Helper.Num() > Limit)
        {
            ++GAIPerceptionCounts.ContainerElementLimitHits;
        }
        for (int32 Index = 0; Index < Limit; ++Index)
        {
            UObject* Config = ConfigInner->GetObjectPropertyValue(Helper.GetRawPtr(Index));
            if (!Config)
            {
                continue;
            }
            if (!ClassInheritsName(Config->GetClass(), TEXT("AISenseConfig")))
            {
                continue;
            }
            if (!AIPerceptionWriteSenseConfig(BlueprintPath, Component->GetPathName(), ConfigCount, Config, OutError))
            {
                return false;
            }
            ++ConfigCount;
        }
    }

    UObject* DominantSense = GetObjectField(Component, FName(TEXT("DominantSense")));
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("blueprint_path"), BlueprintPath);
    Row->SetStringField(TEXT("generated_class"), GeneratedClass ? GeneratedClass->GetPathName() : FString());
    Row->SetStringField(TEXT("component_path"), Component->GetPathName());
    Row->SetStringField(TEXT("component_name"), Component->GetName());
    Row->SetStringField(TEXT("component_class"), Component->GetClass()->GetPathName());
    Row->SetStringField(TEXT("dominant_sense_class"), DominantSense ? DominantSense->GetPathName() : FString());
    Row->SetNumberField(TEXT("sense_config_count"), ConfigCount);
    Row->SetNumberField(TEXT("property_count"), PropertyCount);
    if (!GAIPerceptionWriters.Components.Write(Row))
    {
        OutError = TEXT("failed writing AI Perception component row: ") + Component->GetPathName();
        return false;
    }
    ++GAIPerceptionCounts.Components;
    return true;
}

static bool AIPerceptionWriteStimuliSource(
    const FString& BlueprintPath,
    UClass* GeneratedClass,
    UObject* Component,
    FString& OutError)
{
    if (!Component)
    {
        return true;
    }

    int32 PropertyCount = 0;
    if (!AIPerceptionWriteProperties(
            BlueprintPath,
            Component,
            TEXT("stimuli_source_component_template"),
            PropertyCount))
    {
        OutError = TEXT("failed writing AI Perception stimuli-source properties: ") + Component->GetPathName();
        return false;
    }

    bool bAutoRegister = false;
    AIPerceptionTryBoolField(Component, FName(TEXT("bAutoRegisterAsSource")), bAutoRegister);

    int32 RegisteredCount = 0;
    const FArrayProperty* SensesArray = CastField<FArrayProperty>(
        Component->GetClass()->FindPropertyByName(FName(TEXT("RegisterAsSourceForSenses"))));
    const FObjectPropertyBase* SensesInner = SensesArray
        ? CastField<FObjectPropertyBase>(SensesArray->Inner)
        : nullptr;
    const void* SensesValue = SensesArray ? SensesArray->ContainerPtrToValuePtr<void>(Component) : nullptr;
    if (SensesArray && SensesInner && SensesValue)
    {
        FScriptArrayHelper Helper(SensesArray, SensesValue);
        const int32 Limit = FMath::Min(Helper.Num(), AIPerceptionMaxElementsPerContainer);
        if (Helper.Num() > Limit)
        {
            ++GAIPerceptionCounts.ContainerElementLimitHits;
        }
        for (int32 Index = 0; Index < Limit; ++Index)
        {
            UObject* Sense = SensesInner->GetObjectPropertyValue(Helper.GetRawPtr(Index));
            TSharedRef<FJsonObject> SenseRow = MakeShared<FJsonObject>();
            SenseRow->SetStringField(TEXT("blueprint_path"), BlueprintPath);
            SenseRow->SetStringField(TEXT("component_path"), Component->GetPathName());
            SenseRow->SetNumberField(TEXT("sense_index"), Index);
            SenseRow->SetStringField(TEXT("sense_class"), Sense ? Sense->GetPathName() : FString());
            SenseRow->SetBoolField(TEXT("is_null"), Sense == nullptr);
            if (!GAIPerceptionWriters.RegisteredSenses.Write(SenseRow))
            {
                OutError = FString::Printf(
                    TEXT("failed writing AI Perception registered sense %s[%d]"),
                    *Component->GetPathName(),
                    Index);
                return false;
            }
            ++RegisteredCount;
            ++GAIPerceptionCounts.RegisteredSenses;
        }
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("blueprint_path"), BlueprintPath);
    Row->SetStringField(TEXT("generated_class"), GeneratedClass ? GeneratedClass->GetPathName() : FString());
    Row->SetStringField(TEXT("component_path"), Component->GetPathName());
    Row->SetStringField(TEXT("component_name"), Component->GetName());
    Row->SetStringField(TEXT("component_class"), Component->GetClass()->GetPathName());
    Row->SetBoolField(TEXT("auto_register_as_source"), bAutoRegister);
    Row->SetNumberField(TEXT("registered_sense_count"), RegisteredCount);
    Row->SetNumberField(TEXT("property_count"), PropertyCount);
    if (!GAIPerceptionWriters.StimuliSources.Write(Row))
    {
        OutError = TEXT("failed writing AI Perception stimuli-source row: ") + Component->GetPathName();
        return false;
    }
    ++GAIPerceptionCounts.StimuliSources;
    return true;
}

static bool ScanAIPerceptionBlueprint(
    const FAssetData& Asset,
    UBlueprint* Blueprint,
    FString& OutError)
{
    if (!Blueprint)
    {
        return true;
    }
    UClass* GeneratedClass = Blueprint->GeneratedClass.Get();
    if (!GeneratedClass)
    {
        return true;
    }

    TArray<UObject*> OwnedObjects;
    GetObjectsWithOuter(
        GeneratedClass,
        OwnedObjects,
        EGetObjectsFlags::IncludeNestedObjects,
        RF_Transient,
        EInternalObjectFlags::Garbage);
    OwnedObjects.Sort([](const UObject& A, const UObject& B)
    {
        return A.GetPathName() < B.GetPathName();
    });

    const int32 Limit = FMath::Min(OwnedObjects.Num(), AIPerceptionMaxObjectsPerBlueprint);
    if (OwnedObjects.Num() > Limit)
    {
        ++GAIPerceptionCounts.ContainerElementLimitHits;
    }
    const FString BlueprintPath = Asset.GetSoftObjectPath().ToString();
    for (int32 Index = 0; Index < Limit; ++Index)
    {
        UObject* Object = OwnedObjects[Index];
        if (!Object || Object->HasAnyFlags(RF_Transient | RF_ClassDefaultObject))
        {
            continue;
        }
        if (Object->IsA<UClass>() || Object->IsA<UPackage>())
        {
            continue;
        }
        const UClass* Class = Object->GetClass();
        if (ClassInheritsName(Class, TEXT("AIPerceptionStimuliSourceComponent")))
        {
            if (!AIPerceptionWriteStimuliSource(BlueprintPath, GeneratedClass, Object, OutError))
            {
                return false;
            }
        }
        else if (ClassInheritsName(Class, TEXT("AIPerceptionComponent")))
        {
            if (!AIPerceptionWriteComponent(BlueprintPath, GeneratedClass, Object, OutError))
            {
                return false;
            }
        }
    }
    return true;
}

static bool ScanAIPerceptionProjectModel(
    const TArray<FAssetData>& Assets,
    const FString& ProjectDir,
    bool bIncludeEngine,
    bool bIncludeSelf,
    const FString& ToolPluginDir,
    FString& OutError)
{
    for (const FAssetData& Asset : Assets)
    {
        if (!AIPerceptionBlueprintCandidate(Asset))
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
        if (!ScanAIPerceptionBlueprint(Asset, Blueprint, OutError))
        {
            return false;
        }
    }
    return true;
}
