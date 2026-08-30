static bool ScanInputProcessorArray(
    UStruct* Struct,
    const void* Value,
    UObject* Owner,
    const FName FieldName,
    const FString& AssetPath,
    const FString& OwnerScope,
    int32 MappingIndex,
    const FString& ProcessorKind,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Struct || !Value)
    {
        return true;
    }
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Struct->FindPropertyByName(FieldName));
    if (!ArrayProperty)
    {
        return true;
    }
    const FObjectPropertyBase* InnerObject = CastField<FObjectPropertyBase>(ArrayProperty->Inner);
    if (!InnerObject)
    {
        return true;
    }
    const void* ValuePtr = ArrayProperty->ContainerPtrToValuePtr<void>(Value);
    if (!ValuePtr)
    {
        return true;
    }

    FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
    const int32 Limit = FMath::Min(Helper.Num(), 4096);
    for (int32 Index = 0; Index < Limit; ++Index)
    {
        UObject* Processor = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
        if (!Processor)
        {
            continue;
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("asset_path"), AssetPath);
        Row->SetStringField(TEXT("owner_scope"), OwnerScope);
        Row->SetNumberField(TEXT("mapping_index"), MappingIndex);
        Row->SetStringField(TEXT("processor_kind"), ProcessorKind);
        Row->SetNumberField(TEXT("processor_index"), Index);
        Row->SetStringField(TEXT("processor_path"), Processor->GetPathName());
        Row->SetStringField(TEXT("processor_class"), Processor->GetClass()->GetPathName());
        if (!Writers.InputProcessors.Write(Row))
        {
            return false;
        }
        ++Counts.InputProcessors;
        if (!WriteObjectState(
            Processor,
            AssetPath,
            ProcessorKind == TEXT("trigger") ? TEXT("input_trigger") : TEXT("input_modifier"),
            Writers,
            Counts,
            SeenStateOwners))
        {
            return false;
        }
    }
    return true;
}

static bool ScanInputAction(
    UObject* Action,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Action)
    {
        return true;
    }
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    const int32 TriggerCount = GetArrayCount(Action, TEXT("Triggers"));
    const int32 ModifierCount = GetArrayCount(Action, TEXT("Modifiers"));

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("action_path"), AssetPath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("class_path"), Action->GetClass()->GetPathName());
    Row->SetStringField(TEXT("value_type"), ExportField(Action, TEXT("ValueType")));
    Row->SetStringField(TEXT("consume_input"), ExportFirstField(Action, {TEXT("bConsumeInput"), TEXT("ConsumeInput")}));
    Row->SetStringField(TEXT("trigger_when_paused"), ExportFirstField(Action, {TEXT("bTriggerWhenPaused"), TEXT("TriggerWhenPaused")}));
    Row->SetStringField(TEXT("reserve_all_mappings"), ExportFirstField(Action, {TEXT("bReserveAllMappings"), TEXT("ReserveAllMappings")}));
    Row->SetStringField(TEXT("consume_legacy_keys"), ExportFirstField(Action, {TEXT("TriggerEventsThatConsumeLegacyKeys")}));
    Row->SetNumberField(TEXT("trigger_count"), TriggerCount);
    Row->SetNumberField(TEXT("modifier_count"), ModifierCount);
    if (!Writers.InputActions.Write(Row))
    {
        return false;
    }
    ++Counts.InputActions;

    if (!ScanInputProcessorArray(Action->GetClass(), Action, Action, TEXT("Triggers"), AssetPath,
        TEXT("action"), -1, TEXT("trigger"), Writers, Counts, SeenStateOwners)) return false;
    if (!ScanInputProcessorArray(Action->GetClass(), Action, Action, TEXT("Modifiers"), AssetPath,
        TEXT("action"), -1, TEXT("modifier"), Writers, Counts, SeenStateOwners)) return false;
    return true;
}

static bool ScanInputMappingContext(
    UObject* Context,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Context)
    {
        return true;
    }
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    int32 MappingCount = 0;

    const FArrayProperty* MappingsProperty = CastField<FArrayProperty>(Context->GetClass()->FindPropertyByName(TEXT("Mappings")));
    if (MappingsProperty)
    {
        const FStructProperty* StructProperty = CastField<FStructProperty>(MappingsProperty->Inner);
        const void* ArrayValue = MappingsProperty->ContainerPtrToValuePtr<void>(Context);
        if (StructProperty && StructProperty->Struct && ArrayValue)
        {
            FScriptArrayHelper Helper(MappingsProperty, ArrayValue);
            const int32 Limit = FMath::Min(Helper.Num(), MaxStructuredRowsPerAsset);
            for (int32 Index = 0; Index < Limit; ++Index)
            {
                const void* Item = Helper.GetRawPtr(Index);
                UScriptStruct* Struct = StructProperty->Struct;
                UObject* Action = GetFirstObjectField(Struct, Item, {TEXT("Action")});
                bool bTruncated = false;
                const FString Raw = ExportProperty(StructProperty, Item, Context, bTruncated);

                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("context_path"), AssetPath);
                Row->SetNumberField(TEXT("mapping_index"), MappingCount++);
                Row->SetStringField(TEXT("struct_type"), Struct->GetPathName());
                Row->SetStringField(TEXT("action_path"), Action ? Action->GetPathName() : FString());
                Row->SetStringField(TEXT("action_class"), Action ? Action->GetClass()->GetPathName() : FString());
                Row->SetStringField(TEXT("key"), ExportField(Struct, Item, TEXT("Key"), Context));
                Row->SetNumberField(TEXT("trigger_count"), GetArrayCount(Struct, Item, TEXT("Triggers")));
                Row->SetNumberField(TEXT("modifier_count"), GetArrayCount(Struct, Item, TEXT("Modifiers")));
                Row->SetStringField(TEXT("player_mappable_options"), ExportFirstField(
                    Struct, Item, Context, {TEXT("PlayerMappableOptions"), TEXT("PlayerMappableKeySettings")}));
                Row->SetStringField(TEXT("setting_behavior"), ExportFirstField(
                    Struct, Item, Context, {TEXT("SettingBehavior"), TEXT("PlayerMappableKeySettingBehavior")}));
                Row->SetStringField(TEXT("raw_value"), Raw);
                Row->SetBoolField(TEXT("truncated"), bTruncated);
                if (!Writers.InputMappings.Write(Row))
                {
                    return false;
                }
                ++Counts.InputMappings;

                if (!ScanInputProcessorArray(Struct, Item, Context, TEXT("Triggers"), AssetPath,
                    TEXT("mapping"), Index, TEXT("trigger"), Writers, Counts, SeenStateOwners)) return false;
                if (!ScanInputProcessorArray(Struct, Item, Context, TEXT("Modifiers"), AssetPath,
                    TEXT("mapping"), Index, TEXT("modifier"), Writers, Counts, SeenStateOwners)) return false;
            }
        }
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("context_path"), AssetPath);
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("class_path"), Context->GetClass()->GetPathName());
    Row->SetNumberField(TEXT("mapping_count"), MappingCount);
    Row->SetStringField(TEXT("description"), ExportFirstField(Context, {TEXT("ContextDescription"), TEXT("Description")}));
    if (!Writers.InputMappingContexts.Write(Row))
    {
        return false;
    }
    ++Counts.InputMappingContexts;
    return true;
}

static bool ScanGameplayDataAsset(
    UObject* Object,
    const FAssetData& Asset,
    const FString& Kind,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Object)
    {
        return true;
    }
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    FString RowStructPath;
    int32 RowCount = 0;

    if (UDataTable* Table = Cast<UDataTable>(Object))
    {
        UScriptStruct* RowStruct = Table->GetRowStruct();
        RowStructPath = RowStruct ? RowStruct->GetPathName() : FString();
        RowCount = Table->GetRowMap().Num();

        if (Kind == TEXT("gameplay_tag_table") && RowStruct)
        {
            TArray<FName> Names;
            Table->GetRowMap().GenerateKeyArray(Names);
            Names.Sort(FNameLexicalLess());
            int32 TagIndex = 0;
            for (const FName RowName : Names)
            {
                const uint8* const* Found = Table->GetRowMap().Find(RowName);
                const uint8* RowData = Found ? *Found : nullptr;
                if (!RowData)
                {
                    continue;
                }
                const FString Tag = ExportFirstField(RowStruct, RowData, Object, {TEXT("Tag"), TEXT("GameplayTag")}));
                const FString Comment = ExportFirstField(RowStruct, RowData, Object, {TEXT("DevComment"), TEXT("Comment")}));
                TSharedRef<FJsonObject> TagRow = MakeShared<FJsonObject>();
                TagRow->SetStringField(TEXT("table_path"), AssetPath);
                TagRow->SetNumberField(TEXT("tag_index"), TagIndex++);
                TagRow->SetStringField(TEXT("row_name"), RowName.ToString());
                TagRow->SetStringField(TEXT("tag"), Tag);
                TagRow->SetStringField(TEXT("comment"), Comment);
                TagRow->SetStringField(TEXT("row_struct"), RowStructPath);
                if (!Writers.GameplayTags.Write(TagRow))
                {
                    return false;
                }
                ++Counts.GameplayTags;
            }
        }
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), AssetPath);
    Row->SetStringField(TEXT("gameplay_kind"), Kind);
    Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("row_struct"), RowStructPath);
    Row->SetNumberField(TEXT("row_count"), RowCount);
    Row->SetStringField(TEXT("primary_asset_rules"), ExportFirstField(Object, {TEXT("Rules"), TEXT("AssetRules")}));
    if (!Writers.GameplayDataAssets.Write(Row))
    {
        return false;
    }
    ++Counts.GameplayDataAssets;
    return true;
}
