struct FGASCounts
{
    int64 Abilities = 0;
    int64 AbilityTriggers = 0;
    int64 AbilityCosts = 0;
    int64 AbilitySets = 0;
    int64 AbilitySetAbilities = 0;
    int64 AbilitySetEffects = 0;
    int64 AbilitySetAttributes = 0;
    int64 GameplayEffects = 0;
    int64 GameplayEffectComponents = 0;
    int64 GameplayEffectModifiers = 0;
    int64 GameplayEffectExecutions = 0;
    int64 GameplayEffectExecutionModifiers = 0;
    int64 GameplayEffectCues = 0;
    int64 GameplayCues = 0;
    int64 AttributeSets = 0;
    int64 Attributes = 0;
};

struct FGASWriters
{
    FJsonlWriter Abilities;
    FJsonlWriter AbilityTriggers;
    FJsonlWriter AbilityCosts;
    FJsonlWriter AbilitySets;
    FJsonlWriter AbilitySetAbilities;
    FJsonlWriter AbilitySetEffects;
    FJsonlWriter AbilitySetAttributes;
    FJsonlWriter GameplayEffects;
    FJsonlWriter GameplayEffectComponents;
    FJsonlWriter GameplayEffectModifiers;
    FJsonlWriter GameplayEffectExecutions;
    FJsonlWriter GameplayEffectExecutionModifiers;
    FJsonlWriter GameplayEffectCues;
    FJsonlWriter GameplayCues;
    FJsonlWriter AttributeSets;
    FJsonlWriter Attributes;

    bool Open(const FString& OutputDir)
    {
        return Abilities.Open(FPaths::Combine(OutputDir, TEXT("gas_abilities.jsonl"))) &&
            AbilityTriggers.Open(FPaths::Combine(OutputDir, TEXT("gas_ability_triggers.jsonl"))) &&
            AbilityCosts.Open(FPaths::Combine(OutputDir, TEXT("gas_ability_costs.jsonl"))) &&
            AbilitySets.Open(FPaths::Combine(OutputDir, TEXT("gas_ability_sets.jsonl"))) &&
            AbilitySetAbilities.Open(FPaths::Combine(OutputDir, TEXT("gas_ability_set_abilities.jsonl"))) &&
            AbilitySetEffects.Open(FPaths::Combine(OutputDir, TEXT("gas_ability_set_effects.jsonl"))) &&
            AbilitySetAttributes.Open(FPaths::Combine(OutputDir, TEXT("gas_ability_set_attributes.jsonl"))) &&
            GameplayEffects.Open(FPaths::Combine(OutputDir, TEXT("gas_gameplay_effects.jsonl"))) &&
            GameplayEffectComponents.Open(FPaths::Combine(OutputDir, TEXT("gas_gameplay_effect_components.jsonl"))) &&
            GameplayEffectModifiers.Open(FPaths::Combine(OutputDir, TEXT("gas_gameplay_effect_modifiers.jsonl"))) &&
            GameplayEffectExecutions.Open(FPaths::Combine(OutputDir, TEXT("gas_gameplay_effect_executions.jsonl"))) &&
            GameplayEffectExecutionModifiers.Open(FPaths::Combine(OutputDir, TEXT("gas_gameplay_effect_execution_modifiers.jsonl"))) &&
            GameplayEffectCues.Open(FPaths::Combine(OutputDir, TEXT("gas_gameplay_effect_cues.jsonl"))) &&
            GameplayCues.Open(FPaths::Combine(OutputDir, TEXT("gas_gameplay_cues.jsonl"))) &&
            AttributeSets.Open(FPaths::Combine(OutputDir, TEXT("gas_attribute_sets.jsonl"))) &&
            Attributes.Open(FPaths::Combine(OutputDir, TEXT("gas_attributes.jsonl")));
    }
};

static FGASCounts GGASCounts;
static FGASWriters GGASWriters;

static bool IsGameplayAbilityClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("GameplayAbility"));
}

static bool IsGameplayEffectClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("GameplayEffect"));
}

static bool IsGameplayCueClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("GameplayCueNotify_Static")) ||
        ClassInheritsName(Class, TEXT("GameplayCueNotify_Actor")) ||
        ClassInheritsName(Class, TEXT("GameplayCueNotify"));
}

static bool IsAbilitySetClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("LyraAbilitySet"));
}

static bool IsAttributeSetClass(const UClass* Class)
{
    return ClassInheritsName(Class, TEXT("AttributeSet"));
}

static FString GASAssetTag(const FAssetData& Asset, const TCHAR* Name)
{
    FString Value;
    Asset.GetTagValue(FName(Name), Value);
    return Value;
}

static bool GASBlueprintMetadataCandidate(const FAssetData& Asset)
{
    if (Asset.AssetClassPath != UBlueprint::StaticClass()->GetClassPathName())
    {
        return false;
    }

    // GeneratedClass contains the asset path itself and therefore cannot be
    // used as a candidate signal (e.g. BP_GameplayEffectPad is an Actor).
    const FString Metadata = FString::Join(
        TArray<FString>{
            GASAssetTag(Asset, TEXT("NativeParentClass")),
            GASAssetTag(Asset, TEXT("ParentClass"))
        },
        TEXT("\n"));
    const FString Lower = Metadata.ToLower();
    return Lower.Contains(TEXT("/script/gameplayabilities.gameplayability")) ||
        Lower.Contains(TEXT("/script/gameplayabilities.gameplayeffect")) ||
        Lower.Contains(TEXT("/script/gameplayabilities.gameplaycuenotify")) ||
        Lower.Contains(TEXT("lyragameplayability"));
}

static const FStructProperty* GASStructField(const UStruct* Struct, const void* Value, const FName Name, const void*& OutValue)
{
    OutValue = nullptr;
    if (!Struct || !Value)
    {
        return nullptr;
    }
    const FStructProperty* Property = CastField<FStructProperty>(Struct->FindPropertyByName(Name));
    if (!Property || !Property->Struct)
    {
        return nullptr;
    }
    OutValue = Property->ContainerPtrToValuePtr<void>(Value);
    return OutValue ? Property : nullptr;
}

static FString GASTagName(const UStruct* Struct, const void* Value, UObject* Owner, const FName FieldName)
{
    const void* TagValue = nullptr;
    const FStructProperty* TagProperty = GASStructField(Struct, Value, FieldName, TagValue);
    if (!TagProperty || !TagValue)
    {
        return FString();
    }
    return GetNameField(TagProperty->Struct, TagValue, FName(TEXT("TagName")), Owner);
}

static FString GASTagName(UObject* Object, const FName FieldName)
{
    return Object ? GASTagName(Object->GetClass(), Object, Object, FieldName) : FString();
}

struct FGASAttributeRef
{
    FString Name;
    FString OwnerClass;
    FString RawValue;
};

static FGASAttributeRef GASReadAttribute(
    const UStruct* Struct,
    const void* Value,
    UObject* Owner,
    const FName FieldName)
{
    FGASAttributeRef Result;
    const void* AttributeValue = nullptr;
    const FStructProperty* AttributeProperty = GASStructField(Struct, Value, FieldName, AttributeValue);
    if (!AttributeProperty || !AttributeValue)
    {
        return Result;
    }
    Result.Name = ExportFirstField(
        AttributeProperty->Struct,
        AttributeValue,
        Owner,
        {TEXT("AttributeName")});
    const FReflectedObjectRef AttributeOwner = ReadObjectField(
        AttributeProperty->Struct,
        AttributeValue,
        FName(TEXT("AttributeOwner")));
    Result.OwnerClass = AttributeOwner.Path;
    bool bTruncated = false;
    Result.RawValue = ExportProperty(AttributeProperty, AttributeValue, Owner, bTruncated);
    return Result;
}

static FReflectedObjectRef GASReadObjectField(UObject* Object, const FName FieldName)
{
    if (!Object)
    {
        return FReflectedObjectRef();
    }
    const FProperty* Property = Object->GetClass()->FindPropertyByName(FieldName);
    return Property
        ? ReadObjectReference(Property, Property->ContainerPtrToValuePtr<void>(Object))
        : FReflectedObjectRef();
}

static bool GASWriteAbilityArrayRows(
    const FString& AbilityPath,
    UObject* CDO,
    const FName PropertyName,
    bool bTriggers,
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
    const FStructProperty* InnerStruct = ArrayProperty
        ? CastField<FStructProperty>(ArrayProperty->Inner)
        : nullptr;
    const void* ArrayValue = ArrayProperty
        ? ArrayProperty->ContainerPtrToValuePtr<void>(CDO)
        : nullptr;
    if (!ArrayProperty || !ArrayValue)
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
        if (bTriggers)
        {
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("ability_path"), AbilityPath);
            Row->SetNumberField(TEXT("trigger_index"), Index);
            Row->SetStringField(
                TEXT("trigger_tag"),
                InnerStruct && InnerStruct->Struct
                    ? GASTagName(InnerStruct->Struct, Element, CDO, FName(TEXT("TriggerTag")))
                    : FString());
            Row->SetStringField(
                TEXT("trigger_source"),
                InnerStruct && InnerStruct->Struct
                    ? ExportStructField(InnerStruct->Struct, Element, CDO, {TEXT("TriggerSource")})
                    : FString());
            Row->SetStringField(TEXT("raw_value"), RawValue);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!GGASWriters.AbilityTriggers.Write(Row))
            {
                return false;
            }
            ++GGASCounts.AbilityTriggers;
            continue;
        }

        FReflectedObjectRef Cost;
        if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(ArrayProperty->Inner))
        {
            Cost.Object = ObjectProperty->GetObjectPropertyValue(Element);
            if (Cost.Object)
            {
                Cost.Path = Cost.Object->GetPathName();
                Cost.ClassPath = Cost.Object->GetClass()->GetPathName();
            }
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("ability_path"), AbilityPath);
        Row->SetNumberField(TEXT("cost_index"), Index);
        Row->SetStringField(TEXT("cost_path"), Cost.Path);
        Row->SetStringField(TEXT("cost_class"), Cost.ClassPath);
        Row->SetStringField(TEXT("raw_value"), RawValue);
        Row->SetBoolField(TEXT("truncated"), bTruncated);
        if (!GGASWriters.AbilityCosts.Write(Row))
        {
            return false;
        }
        ++GGASCounts.AbilityCosts;
        if (Cost.Object && !WriteObjectState(
                Cost.Object,
                AbilityPath,
                TEXT("gas_ability_cost"),
                Writers,
                Counts,
                SeenStateOwners))
        {
            return false;
        }
    }
    return true;
}

static bool GASWriteAbility(
    UBlueprint* Blueprint,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Blueprint || !Blueprint->GeneratedClass || !IsGameplayAbilityClass(Blueprint->GeneratedClass))
    {
        return true;
    }
    const FString AbilityPath = Asset.GetSoftObjectPath().ToString();
    UObject* CDO = Blueprint->GeneratedClass->GetDefaultObject(false);
    int32 TriggerCount = 0;
    int32 AdditionalCostCount = 0;
    if (!GASWriteAbilityArrayRows(
            AbilityPath,
            CDO,
            FName(TEXT("AbilityTriggers")),
            true,
            Writers,
            Counts,
            SeenStateOwners,
            TriggerCount) ||
        !GASWriteAbilityArrayRows(
            AbilityPath,
            CDO,
            FName(TEXT("AdditionalCosts")),
            false,
            Writers,
            Counts,
            SeenStateOwners,
            AdditionalCostCount))
    {
        return false;
    }

    const FReflectedObjectRef CostEffect = GASReadObjectField(CDO, FName(TEXT("CostGameplayEffectClass")));
    const FReflectedObjectRef CooldownEffect = GASReadObjectField(CDO, FName(TEXT("CooldownGameplayEffectClass")));

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("ability_path"), AbilityPath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("generated_class"), Blueprint->GeneratedClass->GetPathName());
    Row->SetStringField(
        TEXT("parent_class"),
        Blueprint->ParentClass ? Blueprint->ParentClass->GetPathName() : FString());
    Row->SetStringField(TEXT("cdo_path"), CDO ? CDO->GetPathName() : FString());
    Row->SetStringField(TEXT("activation_policy"), CDO ? ExportFirstField(CDO, {TEXT("ActivationPolicy")}) : FString());
    Row->SetStringField(TEXT("activation_group"), CDO ? ExportFirstField(CDO, {TEXT("ActivationGroup")}) : FString());
    Row->SetStringField(TEXT("replication_policy"), CDO ? ExportFirstField(CDO, {TEXT("ReplicationPolicy")}) : FString());
    Row->SetStringField(TEXT("instancing_policy"), CDO ? ExportFirstField(CDO, {TEXT("InstancingPolicy")}) : FString());
    Row->SetStringField(TEXT("net_execution_policy"), CDO ? ExportFirstField(CDO, {TEXT("NetExecutionPolicy")}) : FString());
    Row->SetStringField(TEXT("net_security_policy"), CDO ? ExportFirstField(CDO, {TEXT("NetSecurityPolicy")}) : FString());
    Row->SetStringField(TEXT("ability_tags"), CDO ? ExportFirstField(CDO, {TEXT("AbilityTags")}) : FString());
    Row->SetStringField(TEXT("cancel_abilities_with_tag"), CDO ? ExportFirstField(CDO, {TEXT("CancelAbilitiesWithTag")}) : FString());
    Row->SetStringField(TEXT("block_abilities_with_tag"), CDO ? ExportFirstField(CDO, {TEXT("BlockAbilitiesWithTag")}) : FString());
    Row->SetStringField(TEXT("activation_owned_tags"), CDO ? ExportFirstField(CDO, {TEXT("ActivationOwnedTags")}) : FString());
    Row->SetStringField(TEXT("activation_required_tags"), CDO ? ExportFirstField(CDO, {TEXT("ActivationRequiredTags")}) : FString());
    Row->SetStringField(TEXT("activation_blocked_tags"), CDO ? ExportFirstField(CDO, {TEXT("ActivationBlockedTags")}) : FString());
    Row->SetStringField(TEXT("source_required_tags"), CDO ? ExportFirstField(CDO, {TEXT("SourceRequiredTags")}) : FString());
    Row->SetStringField(TEXT("source_blocked_tags"), CDO ? ExportFirstField(CDO, {TEXT("SourceBlockedTags")}) : FString());
    Row->SetStringField(TEXT("target_required_tags"), CDO ? ExportFirstField(CDO, {TEXT("TargetRequiredTags")}) : FString());
    Row->SetStringField(TEXT("target_blocked_tags"), CDO ? ExportFirstField(CDO, {TEXT("TargetBlockedTags")}) : FString());
    Row->SetStringField(TEXT("cost_gameplay_effect_class"), CostEffect.Path);
    Row->SetStringField(TEXT("cooldown_gameplay_effect_class"), CooldownEffect.Path);
    Row->SetNumberField(TEXT("trigger_count"), TriggerCount);
    Row->SetNumberField(TEXT("additional_cost_count"), AdditionalCostCount);
    if (!GGASWriters.Abilities.Write(Row))
    {
        return false;
    }
    ++GGASCounts.Abilities;
    return !CDO || WriteObjectState(
        CDO,
        AbilityPath,
        TEXT("gas_ability"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool GASWriteAbilitySetArray(
    UObject* AbilitySet,
    const FString& AbilitySetPath,
    const FName PropertyName,
    int32 Kind,
    int32& OutCount)
{
    OutCount = 0;
    if (!AbilitySet)
    {
        return true;
    }
    const FArrayProperty* ArrayProperty =
        CastField<FArrayProperty>(AbilitySet->GetClass()->FindPropertyByName(PropertyName));
    const FStructProperty* InnerStruct = ArrayProperty
        ? CastField<FStructProperty>(ArrayProperty->Inner)
        : nullptr;
    const void* ArrayValue = ArrayProperty
        ? ArrayProperty->ContainerPtrToValuePtr<void>(AbilitySet)
        : nullptr;
    if (!ArrayProperty || !InnerStruct || !InnerStruct->Struct || !ArrayValue)
    {
        return true;
    }

    FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
    OutCount = Helper.Num();
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Element = Helper.GetRawPtr(Index);
        bool bTruncated = false;
        const FString RawValue = ExportArrayElement(ArrayProperty, Element, AbilitySet, bTruncated);
        if (Kind == 0)
        {
            const FReflectedObjectRef Ability = ReadObjectField(
                InnerStruct->Struct,
                Element,
                FName(TEXT("Ability")));
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("ability_set_path"), AbilitySetPath);
            Row->SetNumberField(TEXT("grant_index"), Index);
            Row->SetStringField(TEXT("ability_class"), Ability.Path);
            Row->SetStringField(
                TEXT("input_tag"),
                GASTagName(InnerStruct->Struct, Element, AbilitySet, FName(TEXT("InputTag"))));
            Row->SetStringField(TEXT("raw_value"), RawValue);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!GGASWriters.AbilitySetAbilities.Write(Row)) return false;
            ++GGASCounts.AbilitySetAbilities;
        }
        else if (Kind == 1)
        {
            const FReflectedObjectRef Effect = ReadObjectField(
                InnerStruct->Struct,
                Element,
                FName(TEXT("GameplayEffect")));
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("ability_set_path"), AbilitySetPath);
            Row->SetNumberField(TEXT("grant_index"), Index);
            Row->SetStringField(TEXT("gameplay_effect_class"), Effect.Path);
            Row->SetStringField(TEXT("raw_value"), RawValue);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!GGASWriters.AbilitySetEffects.Write(Row)) return false;
            ++GGASCounts.AbilitySetEffects;
        }
        else
        {
            const FReflectedObjectRef AttributeSet = ReadObjectField(
                InnerStruct->Struct,
                Element,
                FName(TEXT("AttributeSet")));
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("ability_set_path"), AbilitySetPath);
            Row->SetNumberField(TEXT("grant_index"), Index);
            Row->SetStringField(TEXT("attribute_set_class"), AttributeSet.Path);
            Row->SetStringField(TEXT("raw_value"), RawValue);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!GGASWriters.AbilitySetAttributes.Write(Row)) return false;
            ++GGASCounts.AbilitySetAttributes;
        }
    }
    return true;
}

static bool GASWriteAbilitySet(
    UObject* AbilitySet,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!AbilitySet || !IsAbilitySetClass(AbilitySet->GetClass()))
    {
        return true;
    }
    const FString Path = Asset.GetSoftObjectPath().ToString();
    int32 AbilityCount = 0;
    int32 EffectCount = 0;
    int32 AttributeCount = 0;
    if (!GASWriteAbilitySetArray(AbilitySet, Path, FName(TEXT("GrantedGameplayAbilities")), 0, AbilityCount) ||
        !GASWriteAbilitySetArray(AbilitySet, Path, FName(TEXT("GrantedGameplayEffects")), 1, EffectCount) ||
        !GASWriteAbilitySetArray(AbilitySet, Path, FName(TEXT("GrantedAttributes")), 2, AttributeCount))
    {
        return false;
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("ability_set_path"), Path);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("class_path"), AbilitySet->GetClass()->GetPathName());
    Row->SetNumberField(TEXT("ability_count"), AbilityCount);
    Row->SetNumberField(TEXT("gameplay_effect_count"), EffectCount);
    Row->SetNumberField(TEXT("attribute_set_count"), AttributeCount);
    if (!GGASWriters.AbilitySets.Write(Row))
    {
        return false;
    }
    ++GGASCounts.AbilitySets;
    return WriteObjectState(
        AbilitySet,
        Path,
        TEXT("gas_ability_set"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool GASWriteGameplayEffectComponents(
    const FString& EffectPath,
    UObject* CDO,
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
        CastField<FArrayProperty>(CDO->GetClass()->FindPropertyByName(FName(TEXT("GEComponents"))));
    const void* ArrayValue = ArrayProperty
        ? ArrayProperty->ContainerPtrToValuePtr<void>(CDO)
        : nullptr;
    if (!ArrayProperty || !ArrayValue)
    {
        return true;
    }
    FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
    OutCount = Helper.Num();
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        FReflectedObjectRef Component = ReadObjectReference(ArrayProperty->Inner, Helper.GetRawPtr(Index));
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("gameplay_effect_path"), EffectPath);
        Row->SetNumberField(TEXT("component_index"), Index);
        Row->SetStringField(TEXT("component_path"), Component.Path);
        Row->SetStringField(TEXT("component_class"), Component.ClassPath);
        Row->SetStringField(TEXT("asset_tags"), Component.Object ? ExportFirstField(Component.Object, {TEXT("InheritableAssetTags"), TEXT("InheritableGameplayEffectTags")}) : FString());
        Row->SetStringField(TEXT("target_tags"), Component.Object ? ExportFirstField(Component.Object, {TEXT("InheritableGrantedTags"), TEXT("InheritableOwnedTagsContainer")}) : FString());
        if (!GGASWriters.GameplayEffectComponents.Write(Row)) return false;
        ++GGASCounts.GameplayEffectComponents;
        if (Component.Object && !WriteObjectState(
                Component.Object,
                EffectPath,
                TEXT("gas_gameplay_effect_component"),
                Writers,
                Counts,
                SeenStateOwners))
        {
            return false;
        }
    }
    return true;
}

static bool GASWriteGameplayEffectModifiers(
    const FString& EffectPath,
    UObject* CDO,
    int32& OutCount)
{
    OutCount = 0;
    if (!CDO) return true;
    const FArrayProperty* ArrayProperty =
        CastField<FArrayProperty>(CDO->GetClass()->FindPropertyByName(FName(TEXT("Modifiers"))));
    const FStructProperty* InnerStruct = ArrayProperty
        ? CastField<FStructProperty>(ArrayProperty->Inner)
        : nullptr;
    const void* ArrayValue = ArrayProperty
        ? ArrayProperty->ContainerPtrToValuePtr<void>(CDO)
        : nullptr;
    if (!ArrayProperty || !InnerStruct || !InnerStruct->Struct || !ArrayValue) return true;
    FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
    OutCount = Helper.Num();
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Element = Helper.GetRawPtr(Index);
        bool bTruncated = false;
        const FGASAttributeRef Attribute = GASReadAttribute(
            InnerStruct->Struct,
            Element,
            CDO,
            FName(TEXT("Attribute")));
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("gameplay_effect_path"), EffectPath);
        Row->SetNumberField(TEXT("modifier_index"), Index);
        Row->SetStringField(TEXT("attribute_name"), Attribute.Name);
        Row->SetStringField(TEXT("attribute_owner_class"), Attribute.OwnerClass);
        Row->SetStringField(TEXT("modifier_op"), ExportStructField(InnerStruct->Struct, Element, CDO, {TEXT("ModifierOp")}));
        Row->SetStringField(TEXT("magnitude"), ExportStructField(InnerStruct->Struct, Element, CDO, {TEXT("ModifierMagnitude")}));
        Row->SetStringField(TEXT("raw_value"), ExportArrayElement(ArrayProperty, Element, CDO, bTruncated));
        Row->SetBoolField(TEXT("truncated"), bTruncated);
        if (!GGASWriters.GameplayEffectModifiers.Write(Row)) return false;
        ++GGASCounts.GameplayEffectModifiers;
    }
    return true;
}

static bool GASWriteExecutionModifiers(
    const FString& EffectPath,
    int32 ExecutionIndex,
    const UStruct* ExecutionStruct,
    const void* ExecutionValue,
    UObject* CDO,
    int32& OutCount)
{
    OutCount = 0;
    if (!ExecutionStruct || !ExecutionValue || !CDO) return true;
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(
        ExecutionStruct->FindPropertyByName(FName(TEXT("CalculationModifiers"))));
    const FStructProperty* InnerStruct = ArrayProperty
        ? CastField<FStructProperty>(ArrayProperty->Inner)
        : nullptr;
    const void* ArrayValue = ArrayProperty
        ? ArrayProperty->ContainerPtrToValuePtr<void>(ExecutionValue)
        : nullptr;
    if (!ArrayProperty || !InnerStruct || !InnerStruct->Struct || !ArrayValue) return true;
    FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
    OutCount = Helper.Num();
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Element = Helper.GetRawPtr(Index);
        const void* CaptureValue = nullptr;
        const FStructProperty* CaptureProperty = GASStructField(
            InnerStruct->Struct,
            Element,
            FName(TEXT("CapturedAttribute")),
            CaptureValue);
        FGASAttributeRef Attribute;
        FString Snapshot;
        if (CaptureProperty && CaptureValue)
        {
            Attribute = GASReadAttribute(
                CaptureProperty->Struct,
                CaptureValue,
                CDO,
                FName(TEXT("AttributeToCapture")));
            Snapshot = ExportStructField(
                CaptureProperty->Struct,
                CaptureValue,
                CDO,
                {TEXT("bSnapshot")});
        }
        bool bTruncated = false;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("gameplay_effect_path"), EffectPath);
        Row->SetNumberField(TEXT("execution_index"), ExecutionIndex);
        Row->SetNumberField(TEXT("modifier_index"), Index);
        Row->SetStringField(TEXT("attribute_name"), Attribute.Name);
        Row->SetStringField(TEXT("attribute_owner_class"), Attribute.OwnerClass);
        Row->SetStringField(TEXT("snapshot"), Snapshot);
        Row->SetStringField(TEXT("modifier_op"), ExportStructField(InnerStruct->Struct, Element, CDO, {TEXT("ModifierOp")}));
        Row->SetStringField(TEXT("magnitude"), ExportStructField(InnerStruct->Struct, Element, CDO, {TEXT("ModifierMagnitude")}));
        Row->SetStringField(TEXT("raw_value"), ExportArrayElement(ArrayProperty, Element, CDO, bTruncated));
        Row->SetBoolField(TEXT("truncated"), bTruncated);
        if (!GGASWriters.GameplayEffectExecutionModifiers.Write(Row)) return false;
        ++GGASCounts.GameplayEffectExecutionModifiers;
    }
    return true;
}

static bool GASWriteGameplayEffectExecutions(
    const FString& EffectPath,
    UObject* CDO,
    int32& OutCount)
{
    OutCount = 0;
    if (!CDO) return true;
    const FArrayProperty* ArrayProperty =
        CastField<FArrayProperty>(CDO->GetClass()->FindPropertyByName(FName(TEXT("Executions"))));
    const FStructProperty* InnerStruct = ArrayProperty
        ? CastField<FStructProperty>(ArrayProperty->Inner)
        : nullptr;
    const void* ArrayValue = ArrayProperty
        ? ArrayProperty->ContainerPtrToValuePtr<void>(CDO)
        : nullptr;
    if (!ArrayProperty || !InnerStruct || !InnerStruct->Struct || !ArrayValue) return true;
    FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
    OutCount = Helper.Num();
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Element = Helper.GetRawPtr(Index);
        const FReflectedObjectRef CalculationClass = ReadObjectField(
            InnerStruct->Struct,
            Element,
            FName(TEXT("CalculationClass")));
        int32 ModifierCount = 0;
        if (!GASWriteExecutionModifiers(
                EffectPath,
                Index,
                InnerStruct->Struct,
                Element,
                CDO,
                ModifierCount))
        {
            return false;
        }
        bool bTruncated = false;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("gameplay_effect_path"), EffectPath);
        Row->SetNumberField(TEXT("execution_index"), Index);
        Row->SetStringField(TEXT("calculation_class"), CalculationClass.Path);
        Row->SetNumberField(TEXT("modifier_count"), ModifierCount);
        Row->SetStringField(TEXT("passed_in_tags"), ExportStructField(InnerStruct->Struct, Element, CDO, {TEXT("PassedInTags")}));
        Row->SetStringField(TEXT("raw_value"), ExportArrayElement(ArrayProperty, Element, CDO, bTruncated));
        Row->SetBoolField(TEXT("truncated"), bTruncated);
        if (!GGASWriters.GameplayEffectExecutions.Write(Row)) return false;
        ++GGASCounts.GameplayEffectExecutions;
    }
    return true;
}

static bool GASWriteGameplayEffectCues(
    const FString& EffectPath,
    UObject* CDO,
    int32& OutCount)
{
    OutCount = 0;
    if (!CDO) return true;
    const FArrayProperty* ArrayProperty =
        CastField<FArrayProperty>(CDO->GetClass()->FindPropertyByName(FName(TEXT("GameplayCues"))));
    const FStructProperty* InnerStruct = ArrayProperty
        ? CastField<FStructProperty>(ArrayProperty->Inner)
        : nullptr;
    const void* ArrayValue = ArrayProperty
        ? ArrayProperty->ContainerPtrToValuePtr<void>(CDO)
        : nullptr;
    if (!ArrayProperty || !InnerStruct || !InnerStruct->Struct || !ArrayValue) return true;
    FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
    OutCount = Helper.Num();
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Element = Helper.GetRawPtr(Index);
        const FGASAttributeRef MagnitudeAttribute = GASReadAttribute(
            InnerStruct->Struct,
            Element,
            CDO,
            FName(TEXT("MagnitudeAttribute")));
        bool bTruncated = false;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("gameplay_effect_path"), EffectPath);
        Row->SetNumberField(TEXT("cue_index"), Index);
        Row->SetStringField(TEXT("gameplay_cue_tags"), ExportStructField(InnerStruct->Struct, Element, CDO, {TEXT("GameplayCueTags")}));
        Row->SetStringField(TEXT("magnitude_attribute_name"), MagnitudeAttribute.Name);
        Row->SetStringField(TEXT("magnitude_attribute_owner_class"), MagnitudeAttribute.OwnerClass);
        Row->SetStringField(TEXT("min_level"), ExportStructField(InnerStruct->Struct, Element, CDO, {TEXT("MinLevel")}));
        Row->SetStringField(TEXT("max_level"), ExportStructField(InnerStruct->Struct, Element, CDO, {TEXT("MaxLevel")}));
        Row->SetStringField(TEXT("raw_value"), ExportArrayElement(ArrayProperty, Element, CDO, bTruncated));
        Row->SetBoolField(TEXT("truncated"), bTruncated);
        if (!GGASWriters.GameplayEffectCues.Write(Row)) return false;
        ++GGASCounts.GameplayEffectCues;
    }
    return true;
}

static bool GASWriteGameplayEffect(
    UBlueprint* Blueprint,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Blueprint || !Blueprint->GeneratedClass || !IsGameplayEffectClass(Blueprint->GeneratedClass))
    {
        return true;
    }
    const FString EffectPath = Asset.GetSoftObjectPath().ToString();
    UObject* CDO = Blueprint->GeneratedClass->GetDefaultObject(false);
    int32 ComponentCount = 0;
    int32 ModifierCount = 0;
    int32 ExecutionCount = 0;
    int32 CueCount = 0;
    if (!GASWriteGameplayEffectComponents(
            EffectPath,
            CDO,
            Writers,
            Counts,
            SeenStateOwners,
            ComponentCount) ||
        !GASWriteGameplayEffectModifiers(EffectPath, CDO, ModifierCount) ||
        !GASWriteGameplayEffectExecutions(EffectPath, CDO, ExecutionCount) ||
        !GASWriteGameplayEffectCues(EffectPath, CDO, CueCount))
    {
        return false;
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("gameplay_effect_path"), EffectPath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("generated_class"), Blueprint->GeneratedClass->GetPathName());
    Row->SetStringField(
        TEXT("parent_class"),
        Blueprint->ParentClass ? Blueprint->ParentClass->GetPathName() : FString());
    Row->SetStringField(TEXT("cdo_path"), CDO ? CDO->GetPathName() : FString());
    Row->SetStringField(TEXT("duration_policy"), CDO ? ExportFirstField(CDO, {TEXT("DurationPolicy")}) : FString());
    Row->SetStringField(TEXT("duration_magnitude"), CDO ? ExportFirstField(CDO, {TEXT("DurationMagnitude")}) : FString());
    Row->SetStringField(TEXT("period"), CDO ? ExportFirstField(CDO, {TEXT("Period")}) : FString());
    Row->SetStringField(TEXT("execute_periodic_on_application"), CDO ? ExportFirstField(CDO, {TEXT("bExecutePeriodicEffectOnApplication")}) : FString());
    Row->SetStringField(TEXT("periodic_inhibition_policy"), CDO ? ExportFirstField(CDO, {TEXT("PeriodicInhibitionPolicy")}) : FString());
    Row->SetStringField(TEXT("effect_tags"), CDO ? ExportFirstField(CDO, {TEXT("InheritableGameplayEffectTags")}) : FString());
    Row->SetStringField(TEXT("owned_tags"), CDO ? ExportFirstField(CDO, {TEXT("InheritableOwnedTagsContainer")}) : FString());
    Row->SetStringField(TEXT("blocked_ability_tags"), CDO ? ExportFirstField(CDO, {TEXT("InheritableBlockedAbilityTagsContainer")}) : FString());
    Row->SetStringField(TEXT("ongoing_tag_requirements"), CDO ? ExportFirstField(CDO, {TEXT("OngoingTagRequirements")}) : FString());
    Row->SetStringField(TEXT("application_tag_requirements"), CDO ? ExportFirstField(CDO, {TEXT("ApplicationTagRequirements")}) : FString());
    Row->SetStringField(TEXT("removal_tag_requirements"), CDO ? ExportFirstField(CDO, {TEXT("RemovalTagRequirements")}) : FString());
    Row->SetStringField(TEXT("stacking_type"), CDO ? ExportFirstField(CDO, {TEXT("StackingType")}) : FString());
    Row->SetStringField(TEXT("stack_limit_count"), CDO ? ExportFirstField(CDO, {TEXT("StackLimitCount")}) : FString());
    Row->SetNumberField(TEXT("component_count"), ComponentCount);
    Row->SetNumberField(TEXT("modifier_count"), ModifierCount);
    Row->SetNumberField(TEXT("execution_count"), ExecutionCount);
    Row->SetNumberField(TEXT("cue_count"), CueCount);
    if (!GGASWriters.GameplayEffects.Write(Row)) return false;
    ++GGASCounts.GameplayEffects;
    return !CDO || WriteObjectState(
        CDO,
        EffectPath,
        TEXT("gas_gameplay_effect"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool GASWriteGameplayCue(
    UBlueprint* Blueprint,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Blueprint || !Blueprint->GeneratedClass || !IsGameplayCueClass(Blueprint->GeneratedClass))
    {
        return true;
    }
    const FString Path = Asset.GetSoftObjectPath().ToString();
    UObject* CDO = Blueprint->GeneratedClass->GetDefaultObject(false);
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("gameplay_cue_path"), Path);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("generated_class"), Blueprint->GeneratedClass->GetPathName());
    Row->SetStringField(TEXT("parent_class"), Blueprint->ParentClass ? Blueprint->ParentClass->GetPathName() : FString());
    Row->SetStringField(TEXT("cdo_path"), CDO ? CDO->GetPathName() : FString());
    Row->SetStringField(TEXT("gameplay_cue_tag"), CDO ? GASTagName(CDO, FName(TEXT("GameplayCueTag"))) : FString());
    Row->SetStringField(TEXT("gameplay_cue_name"), CDO ? ExportFirstField(CDO, {TEXT("GameplayCueName")}) : FString());
    Row->SetStringField(TEXT("is_override"), CDO ? ExportFirstField(CDO, {TEXT("IsOverride")}) : FString());
    if (!GGASWriters.GameplayCues.Write(Row)) return false;
    ++GGASCounts.GameplayCues;
    return !CDO || WriteObjectState(
        CDO,
        Path,
        TEXT("gas_gameplay_cue"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool GASWriteAttributeSetClass(
    UClass* Class,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Class || !IsAttributeSetClass(Class) ||
        Class->HasAnyClassFlags(CLASS_Deprecated | CLASS_NewerVersionExists))
    {
        return true;
    }

    UObject* CDO = Class->GetDefaultObject(false);
    int32 AttributeCount = 0;
    for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
    {
        FProperty* Property = *It;
        if (!Property || Property->GetOwnerStruct() != Class || !ShouldInspectProperty(Property))
        {
            continue;
        }
        const FStructProperty* StructProperty = CastField<FStructProperty>(Property);
        if (!StructProperty || !StructProperty->Struct ||
            !StructProperty->Struct->GetName().Equals(TEXT("GameplayAttributeData"), ESearchCase::CaseSensitive))
        {
            continue;
        }
        const void* Value = CDO ? Property->ContainerPtrToValuePtr<void>(CDO) : nullptr;
        TSharedRef<FJsonObject> AttributeRow = MakeShared<FJsonObject>();
        AttributeRow->SetStringField(TEXT("attribute_set_class"), Class->GetPathName());
        AttributeRow->SetNumberField(TEXT("attribute_index"), AttributeCount);
        AttributeRow->SetStringField(TEXT("attribute_name"), Property->GetName());
        AttributeRow->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
        AttributeRow->SetStringField(
            TEXT("base_value"),
            Value ? ExportStructField(StructProperty->Struct, Value, CDO, {TEXT("BaseValue")}) : FString());
        AttributeRow->SetStringField(
            TEXT("current_value"),
            Value ? ExportStructField(StructProperty->Struct, Value, CDO, {TEXT("CurrentValue")}) : FString());
        if (!GGASWriters.Attributes.Write(AttributeRow)) return false;
        ++GGASCounts.Attributes;
        ++AttributeCount;
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("attribute_set_class"), Class->GetPathName());
    Row->SetStringField(TEXT("super_class"), Class->GetSuperClass() ? Class->GetSuperClass()->GetPathName() : FString());
    Row->SetStringField(TEXT("module_package"), Class->GetOutermost() ? Class->GetOutermost()->GetName() : FString());
    Row->SetStringField(TEXT("cdo_path"), CDO ? CDO->GetPathName() : FString());
    Row->SetBoolField(TEXT("native"), Class->HasAnyClassFlags(CLASS_Native));
    Row->SetNumberField(TEXT("attribute_count"), AttributeCount);
    if (!GGASWriters.AttributeSets.Write(Row)) return false;
    ++GGASCounts.AttributeSets;
    return !CDO || WriteObjectState(
        CDO,
        Class->GetPathName(),
        TEXT("gas_attribute_set"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool ScanGASProjectModel(
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

        if (Asset.AssetClassPath == UBlueprint::StaticClass()->GetClassPathName())
        {
            if (!GASBlueprintMetadataCandidate(Asset))
            {
                continue;
            }
            UBlueprint* Blueprint = Cast<UBlueprint>(Asset.GetAsset());
            if (!Blueprint || !Blueprint->GeneratedClass)
            {
                continue;
            }
            if (!GASWriteAbility(Blueprint, Asset, Writers, Counts, SeenStateOwners) ||
                !GASWriteGameplayEffect(Blueprint, Asset, Writers, Counts, SeenStateOwners) ||
                !GASWriteGameplayCue(Blueprint, Asset, Writers, Counts, SeenStateOwners))
            {
                OutError = TEXT("failed while scanning GAS Blueprint ") +
                    Asset.GetSoftObjectPath().ToString();
                return false;
            }
            continue;
        }

        const FString AssetClassPath = Asset.AssetClassPath.ToString();
        if (!AssetClassPath.Contains(TEXT("LyraAbilitySet")))
        {
            continue;
        }
        UObject* Object = Asset.GetAsset();
        if (Object && !GASWriteAbilitySet(
                Object,
                Asset,
                Writers,
                Counts,
                SeenStateOwners))
        {
            OutError = TEXT("failed while scanning GAS ability set ") +
                Asset.GetSoftObjectPath().ToString();
            return false;
        }
    }

    for (TObjectIterator<UClass> It; It; ++It)
    {
        UClass* Class = *It;
        if (!Class || !IsAttributeSetClass(Class))
        {
            continue;
        }
        if (!GASWriteAttributeSetClass(Class, Writers, Counts, SeenStateOwners))
        {
            OutError = TEXT("failed while scanning GAS AttributeSet class ") + Class->GetPathName();
            return false;
        }
    }
    return true;
}
