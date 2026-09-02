struct FSmartObjectCounts
{
    int64 Definitions = 0;
    int64 Slots = 0;
    int64 Behaviors = 0;
    int64 BehaviorProperties = 0;
};

struct FSmartObjectWriters
{
    FJsonlWriter Definitions;
    FJsonlWriter Slots;
    FJsonlWriter Behaviors;
    FJsonlWriter BehaviorProperties;

    bool Open(const FString& OutputDir)
    {
        return Definitions.Open(FPaths::Combine(OutputDir, TEXT("smartobject_definitions.jsonl"))) &&
            Slots.Open(FPaths::Combine(OutputDir, TEXT("smartobject_slots.jsonl"))) &&
            Behaviors.Open(FPaths::Combine(OutputDir, TEXT("smartobject_behaviors.jsonl"))) &&
            BehaviorProperties.Open(FPaths::Combine(OutputDir, TEXT("smartobject_behavior_properties.jsonl")));
    }
};

static FSmartObjectCounts GSmartObjectCounts;
static FSmartObjectWriters GSmartObjectWriters;

static FString SmartObjectAssetTag(const FAssetData& Asset, const TCHAR* Name)
{
    FString Value;
    Asset.GetTagValue(FName(Name), Value);
    return Value;
}

static bool SmartObjectDefinitionMetadataCandidate(const FAssetData& Asset)
{
    const FString Metadata = FString::Join(
        TArray<FString>{
            Asset.AssetClassPath.ToString(),
            SmartObjectAssetTag(Asset, TEXT("NativeClass")),
            SmartObjectAssetTag(Asset, TEXT("NativeParentClass")),
            SmartObjectAssetTag(Asset, TEXT("ParentClass"))
        },
        TEXT("\n"));
    return Metadata.Contains(TEXT("SmartObjectDefinition"), ESearchCase::IgnoreCase);
}

static bool SmartObjectBoolField(const UStruct* Struct, const void* Value, const FName FieldName, bool DefaultValue = false)
{
    if (!Struct || !Value)
    {
        return DefaultValue;
    }
    const FBoolProperty* Property = CastField<FBoolProperty>(Struct->FindPropertyByName(FieldName));
    if (!Property)
    {
        return DefaultValue;
    }
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Value);
    return ValuePtr ? Property->GetPropertyValue(ValuePtr) : DefaultValue;
}

static double SmartObjectNumberField(const UStruct* Struct, const void* Value, const FName FieldName)
{
    if (!Struct || !Value)
    {
        return 0.0;
    }
    const FProperty* Property = Struct->FindPropertyByName(FieldName);
    if (!Property)
    {
        return 0.0;
    }
    bool bTruncated = false;
    const FString Text = ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(Value), nullptr, bTruncated);
    return FCString::Atod(*Text);
}

static const FStructProperty* SmartObjectStructField(
    const UStruct* Struct,
    const void* Value,
    const FName FieldName,
    const void*& OutValue)
{
    OutValue = nullptr;
    if (!Struct || !Value)
    {
        return nullptr;
    }
    const FStructProperty* Property = CastField<FStructProperty>(Struct->FindPropertyByName(FieldName));
    if (!Property || !Property->Struct)
    {
        return nullptr;
    }
    OutValue = Property->ContainerPtrToValuePtr<void>(Value);
    return OutValue ? Property : nullptr;
}

static FString SmartObjectNestedObjectPath(
    const UStruct* Struct,
    const void* Value,
    const FName StructFieldName,
    const FName ObjectFieldName)
{
    const void* NestedValue = nullptr;
    const FStructProperty* NestedProperty = SmartObjectStructField(Struct, Value, StructFieldName, NestedValue);
    if (!NestedProperty || !NestedValue)
    {
        return FString();
    }
    UObject* Target = GetObjectField(NestedProperty->Struct, NestedValue, ObjectFieldName);
    return Target ? Target->GetPathName() : FString();
}

static int32 SmartObjectBehaviorPropertyCount(UObject* Object)
{
    if (!Object)
    {
        return 0;
    }
    int32 Count = 0;
    TSet<FString> Seen;
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
            if (Seen.Contains(Key))
            {
                continue;
            }
            Seen.Add(Key);
            ++Count;
        }
    }
    return Count;
}

static bool SmartObjectWriteBehaviorProperties(const FString& DefinitionPath, UObject* Behavior)
{
    if (!Behavior)
    {
        return true;
    }
    int32 PropertyIndex = 0;
    TSet<FString> Seen;
    for (UClass* Class = Behavior->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property))
            {
                continue;
            }
            const FString Key = Class->GetPathName() + TEXT("::") + Property->GetName();
            if (Seen.Contains(Key))
            {
                continue;
            }
            Seen.Add(Key);

            bool bTruncated = false;
            const FString Value = ExportProperty(
                Property,
                Property->ContainerPtrToValuePtr<void>(Behavior),
                Behavior,
                bTruncated);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("definition_path"), DefinitionPath);
            Row->SetStringField(TEXT("behavior_path"), Behavior->GetPathName());
            Row->SetNumberField(TEXT("property_index"), PropertyIndex++);
            Row->SetStringField(TEXT("declaring_type"), Class->GetPathName());
            Row->SetStringField(TEXT("property_name"), Property->GetName());
            Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
            Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
            Row->SetStringField(TEXT("value"), Value);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!GSmartObjectWriters.BehaviorProperties.Write(Row))
            {
                return false;
            }
            ++GSmartObjectCounts.BehaviorProperties;
        }
    }
    return true;
}

static bool SmartObjectWriteBehavior(
    const FString& DefinitionPath,
    const FString& Scope,
    int32 SlotIndex,
    int32 BehaviorIndex,
    UObject* Behavior,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Behavior)
    {
        return false;
    }
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("definition_path"), DefinitionPath);
    Row->SetStringField(TEXT("scope"), Scope);
    Row->SetNumberField(TEXT("slot_index"), SlotIndex);
    Row->SetNumberField(TEXT("behavior_index"), BehaviorIndex);
    Row->SetStringField(TEXT("behavior_path"), Behavior->GetPathName());
    Row->SetStringField(TEXT("behavior_class"), Behavior->GetClass()->GetPathName());
    Row->SetNumberField(TEXT("property_count"), SmartObjectBehaviorPropertyCount(Behavior));
    if (!GSmartObjectWriters.Behaviors.Write(Row))
    {
        return false;
    }
    ++GSmartObjectCounts.Behaviors;

    if (!SmartObjectWriteBehaviorProperties(DefinitionPath, Behavior))
    {
        return false;
    }
    return WriteObjectState(
        Behavior,
        DefinitionPath,
        TEXT("smart_object_behavior"),
        Writers,
        Counts,
        SeenStateOwners);
}

static bool SmartObjectWriteBehaviorArray(
    const FString& DefinitionPath,
    const FString& Scope,
    int32 SlotIndex,
    const UStruct* Struct,
    const void* Value,
    const FName FieldName,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners,
    int32& OutCount)
{
    OutCount = 0;
    if (!Struct || !Value)
    {
        return true;
    }
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
    const FObjectPropertyBase* InnerObject = ArrayProperty ? CastField<FObjectPropertyBase>(ArrayProperty->Inner) : nullptr;
    const void* ArrayValue = ArrayProperty ? ArrayProperty->ContainerPtrToValuePtr<void>(Value) : nullptr;
    if (!ArrayProperty || !InnerObject || !ArrayValue)
    {
        return true;
    }

    FScriptArrayHelper Helper(ArrayProperty, ArrayValue);
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        UObject* Behavior = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
        if (!Behavior)
        {
            continue;
        }
        const int32 DenseIndex = OutCount++;
        if (!SmartObjectWriteBehavior(
                DefinitionPath,
                Scope,
                SlotIndex,
                DenseIndex,
                Behavior,
                Writers,
                Counts,
                SeenStateOwners))
        {
            return false;
        }
    }
    return true;
}

static bool SmartObjectScanDefinition(
    const FAssetData& Asset,
    UObject* Definition,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners,
    FString& OutError)
{
    if (!Definition || !ClassInheritsName(Definition->GetClass(), TEXT("SmartObjectDefinition")))
    {
        return true;
    }

    const FString DefinitionPath = Asset.GetSoftObjectPath().ToString();
    TSharedRef<FJsonObject> AssetRow = MakeShared<FJsonObject>();
    AssetRow->SetStringField(TEXT("systems_path"), DefinitionPath);
    AssetRow->SetStringField(TEXT("systems_kind"), TEXT("smart_object_definition"));
    AssetRow->SetStringField(TEXT("family"), TEXT("gameplay"));
    AssetRow->SetStringField(TEXT("class_path"), Definition->GetClass()->GetPathName());
    AssetRow->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    if (!Writers.Assets.Write(AssetRow))
    {
        OutError = TEXT("failed writing Smart Object systems asset: ") + DefinitionPath;
        return false;
    }
    ++Counts.Assets;

    if (!WriteObjectState(
            Definition,
            DefinitionPath,
            TEXT("smart_object_definition"),
            Writers,
            Counts,
            SeenStateOwners))
    {
        OutError = TEXT("failed writing Smart Object definition state: ") + DefinitionPath;
        return false;
    }

    int32 DefaultBehaviorCount = 0;
    if (!SmartObjectWriteBehaviorArray(
            DefinitionPath,
            TEXT("default"),
            -1,
            Definition->GetClass(),
            Definition,
            FName(TEXT("DefaultBehaviorDefinitions")),
            Writers,
            Counts,
            SeenStateOwners,
            DefaultBehaviorCount))
    {
        OutError = TEXT("failed writing Smart Object default behaviors: ") + DefinitionPath;
        return false;
    }

    const FArrayProperty* SlotsProperty = CastField<FArrayProperty>(Definition->GetClass()->FindPropertyByName(FName(TEXT("Slots"))));
    const FStructProperty* SlotStructProperty = SlotsProperty ? CastField<FStructProperty>(SlotsProperty->Inner) : nullptr;
    const void* SlotsValue = SlotsProperty ? SlotsProperty->ContainerPtrToValuePtr<void>(Definition) : nullptr;
    const int32 SlotCount = SlotsProperty && SlotStructProperty && SlotStructProperty->Struct && SlotsValue
        ? FScriptArrayHelper(SlotsProperty, SlotsValue).Num()
        : 0;

    TSharedRef<FJsonObject> DefinitionRow = MakeShared<FJsonObject>();
    DefinitionRow->SetStringField(TEXT("definition_path"), DefinitionPath);
    DefinitionRow->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    DefinitionRow->SetStringField(TEXT("class_path"), Definition->GetClass()->GetPathName());
    DefinitionRow->SetNumberField(TEXT("slot_count"), SlotCount);
    DefinitionRow->SetNumberField(TEXT("default_behavior_count"), DefaultBehaviorCount);
    DefinitionRow->SetStringField(TEXT("activity_tags"), ExportFirstField(Definition, {TEXT("ActivityTags")}));
    DefinitionRow->SetStringField(TEXT("user_tag_filter"), ExportFirstField(Definition, {TEXT("UserTagFilter")}));
    DefinitionRow->SetStringField(TEXT("object_tag_filter"), ExportFirstField(Definition, {TEXT("ObjectTagFilter")}));
    DefinitionRow->SetStringField(TEXT("preconditions"), ExportFirstField(Definition, {TEXT("Preconditions")}));
    if (UObject* Schema = GetObjectField(Definition, FName(TEXT("WorldConditionSchemaClass"))))
    {
        DefinitionRow->SetStringField(TEXT("world_condition_schema_class"), Schema->GetPathName());
    }
    else
    {
        DefinitionRow->SetStringField(TEXT("world_condition_schema_class"), FString());
    }
    DefinitionRow->SetStringField(
        TEXT("activity_tags_merging_policy"),
        ExportFirstField(Definition, {TEXT("ActivityTagsMergingPolicy")}));
    DefinitionRow->SetStringField(
        TEXT("user_tags_filtering_policy"),
        ExportFirstField(Definition, {TEXT("UserTagsFilteringPolicy")}));
    if (!GSmartObjectWriters.Definitions.Write(DefinitionRow))
    {
        OutError = TEXT("failed writing Smart Object definition row: ") + DefinitionPath;
        return false;
    }
    ++GSmartObjectCounts.Definitions;

    if (!SlotsProperty || !SlotStructProperty || !SlotStructProperty->Struct || !SlotsValue)
    {
        return true;
    }

    FScriptArrayHelper SlotsHelper(SlotsProperty, SlotsValue);
    for (int32 SlotIndex = 0; SlotIndex < SlotsHelper.Num(); ++SlotIndex)
    {
        const void* SlotValue = SlotsHelper.GetRawPtr(SlotIndex);
        const UStruct* SlotStruct = SlotStructProperty->Struct;
        if (!SlotValue || !SlotStruct)
        {
            OutError = FString::Printf(TEXT("invalid Smart Object slot %s[%d]"), *DefinitionPath, SlotIndex);
            return false;
        }

        int32 SlotBehaviorCount = 0;
        if (!SmartObjectWriteBehaviorArray(
                DefinitionPath,
                TEXT("slot"),
                SlotIndex,
                SlotStruct,
                SlotValue,
                FName(TEXT("BehaviorDefinitions")),
                Writers,
                Counts,
                SeenStateOwners,
                SlotBehaviorCount))
        {
            OutError = FString::Printf(TEXT("failed writing Smart Object slot behaviors %s[%d]"), *DefinitionPath, SlotIndex);
            return false;
        }

        const void* OffsetValue = nullptr;
        const FStructProperty* OffsetProperty = SmartObjectStructField(
            SlotStruct, SlotValue, FName(TEXT("Offset")), OffsetValue);
        const void* RotationValue = nullptr;
        const FStructProperty* RotationProperty = SmartObjectStructField(
            SlotStruct, SlotValue, FName(TEXT("Rotation")), RotationValue);

        TSharedRef<FJsonObject> SlotRow = MakeShared<FJsonObject>();
        SlotRow->SetStringField(TEXT("definition_path"), DefinitionPath);
        SlotRow->SetNumberField(TEXT("slot_index"), SlotIndex);
        SlotRow->SetStringField(TEXT("slot_id"), ExportFirstField(SlotStruct, SlotValue, Definition, {TEXT("ID")}));
        SlotRow->SetStringField(TEXT("name"), GetNameField(SlotStruct, SlotValue, FName(TEXT("Name")), Definition));
        SlotRow->SetBoolField(TEXT("enabled"), SmartObjectBoolField(SlotStruct, SlotValue, FName(TEXT("bEnabled")), true));
        SlotRow->SetNumberField(TEXT("offset_x"), OffsetProperty ? SmartObjectNumberField(OffsetProperty->Struct, OffsetValue, FName(TEXT("X"))) : 0.0);
        SlotRow->SetNumberField(TEXT("offset_y"), OffsetProperty ? SmartObjectNumberField(OffsetProperty->Struct, OffsetValue, FName(TEXT("Y"))) : 0.0);
        SlotRow->SetNumberField(TEXT("offset_z"), OffsetProperty ? SmartObjectNumberField(OffsetProperty->Struct, OffsetValue, FName(TEXT("Z"))) : 0.0);
        SlotRow->SetNumberField(TEXT("rotation_pitch"), RotationProperty ? SmartObjectNumberField(RotationProperty->Struct, RotationValue, FName(TEXT("Pitch"))) : 0.0);
        SlotRow->SetNumberField(TEXT("rotation_yaw"), RotationProperty ? SmartObjectNumberField(RotationProperty->Struct, RotationValue, FName(TEXT("Yaw"))) : 0.0);
        SlotRow->SetNumberField(TEXT("rotation_roll"), RotationProperty ? SmartObjectNumberField(RotationProperty->Struct, RotationValue, FName(TEXT("Roll"))) : 0.0);
        SlotRow->SetStringField(TEXT("user_tag_filter"), ExportFirstField(SlotStruct, SlotValue, Definition, {TEXT("UserTagFilter")}));
        SlotRow->SetStringField(TEXT("activity_tags"), ExportFirstField(SlotStruct, SlotValue, Definition, {TEXT("ActivityTags")}));
        SlotRow->SetStringField(TEXT("runtime_tags"), ExportFirstField(SlotStruct, SlotValue, Definition, {TEXT("RuntimeTags")}));
        SlotRow->SetStringField(TEXT("selection_preconditions"), ExportFirstField(SlotStruct, SlotValue, Definition, {TEXT("SelectionPreconditions")}));
        SlotRow->SetStringField(
            TEXT("selection_schema_class"),
            SmartObjectNestedObjectPath(
                SlotStruct,
                SlotValue,
                FName(TEXT("SelectionPreconditions")),
                FName(TEXT("SchemaClass"))));
        SlotRow->SetNumberField(TEXT("behavior_count"), SlotBehaviorCount);
        SlotRow->SetNumberField(TEXT("definition_data_count"), GetArrayCount(SlotStruct, SlotValue, FName(TEXT("DefinitionData"))));
        if (!GSmartObjectWriters.Slots.Write(SlotRow))
        {
            OutError = FString::Printf(TEXT("failed writing Smart Object slot row %s[%d]"), *DefinitionPath, SlotIndex);
            return false;
        }
        ++GSmartObjectCounts.Slots;
    }
    return true;
}

static bool ScanSmartObjectProjectModel(
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
        if (!SmartObjectDefinitionMetadataCandidate(Asset))
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

        UObject* Definition = Asset.GetAsset();
        if (!Definition || !ClassInheritsName(Definition->GetClass(), TEXT("SmartObjectDefinition")))
        {
            continue;
        }
        if (!SmartObjectScanDefinition(Asset, Definition, Writers, Counts, SeenStateOwners, OutError))
        {
            return false;
        }
    }
    return true;
}
