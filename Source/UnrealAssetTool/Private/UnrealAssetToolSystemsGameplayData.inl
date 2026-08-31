static FString CurveTableModeName(const ECurveTableMode Mode)
{
    switch (Mode)
    {
    case ECurveTableMode::SimpleCurves: return TEXT("simple");
    case ECurveTableMode::RichCurves: return TEXT("rich");
    default: return TEXT("empty");
    }
}

static FString GameplayTagSourceTypeName(const EGameplayTagSourceType Type)
{
    switch (Type)
    {
    case EGameplayTagSourceType::Native: return TEXT("native");
    case EGameplayTagSourceType::DefaultTagList: return TEXT("default_tag_list");
    case EGameplayTagSourceType::TagList: return TEXT("tag_list");
    case EGameplayTagSourceType::RestrictedTagList: return TEXT("restricted_tag_list");
    case EGameplayTagSourceType::DataTable: return TEXT("data_table");
    default: return TEXT("invalid");
    }
}

static void SetFiniteNumberOrNull(
    const TSharedRef<FJsonObject>& Row,
    const TCHAR* Field,
    const double Value)
{
    if (FMath::IsFinite(Value))
    {
        Row->SetNumberField(Field, Value);
    }
    else
    {
        Row->SetField(Field, MakeShared<FJsonValueNull>());
    }
}

static bool ScanDataTableDetails(
    UDataTable* Table,
    const FAssetData& Asset,
    const FString& Kind,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Table)
    {
        return true;
    }

    const FString TablePath = Asset.GetSoftObjectPath().ToString();
    const UScriptStruct* RowStruct = Table->GetRowStruct();
    if (!RowStruct)
    {
        return true;
    }

    TArray<FProperty*> Fields;
    for (TFieldIterator<FProperty> It(RowStruct); It; ++It)
    {
        FProperty* Property = *It;
        if (ShouldInspectProperty(Property))
        {
            Fields.Add(Property);
        }
    }

    TArray<FName> RowNames;
    Table->GetRowMap().GenerateKeyArray(RowNames);
    RowNames.Sort([](const FName& A, const FName& B)
    {
        return A.LexicalLess(B);
    });

    int32 FieldRowsForAsset = 0;
    int32 ReferenceRowsForAsset = 0;
    const int32 RowLimit = FMath::Min(RowNames.Num(), MaxStructuredRowsPerAsset);
    for (int32 RowIndex = 0; RowIndex < RowLimit; ++RowIndex)
    {
        const FName RowName = RowNames[RowIndex];
        uint8* const* Found = Table->GetRowMap().Find(RowName);
        const uint8* RowData = Found ? *Found : nullptr;
        if (!RowData)
        {
            continue;
        }

        const FString RowPath = FString::Printf(TEXT("%s::row[%s]"), *TablePath, *RowName.ToString());
        const int32 RemainingFields = FMath::Max(0, MaxStructuredRowsPerAsset - FieldRowsForAsset);
        const int32 EmittedFieldCount = FMath::Min(Fields.Num(), RemainingFields);

        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("table_path"), TablePath);
        Row->SetStringField(TEXT("table_kind"), Kind);
        Row->SetNumberField(TEXT("row_index"), RowIndex);
        Row->SetStringField(TEXT("row_name"), RowName.ToString());
        Row->SetStringField(TEXT("row_path"), RowPath);
        Row->SetStringField(TEXT("row_struct"), RowStruct->GetPathName());
        Row->SetNumberField(TEXT("field_count"), EmittedFieldCount);
        Row->SetNumberField(TEXT("declared_field_count"), Fields.Num());
        Row->SetBoolField(TEXT("truncated"), EmittedFieldCount != Fields.Num());
        if (!Writers.DataTableRows.Write(Row))
        {
            return false;
        }
        ++Counts.DataTableRows;

        for (int32 FieldIndex = 0; FieldIndex < EmittedFieldCount; ++FieldIndex)
        {
            FProperty* Property = Fields[FieldIndex];
            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(RowData);
            bool bTruncated = false;
            const FString Value = ExportProperty(Property, ValuePtr, Table, bTruncated);
            const UStruct* DeclaringType = Property->GetOwnerStruct();

            TSharedRef<FJsonObject> FieldRow = MakeShared<FJsonObject>();
            FieldRow->SetStringField(TEXT("table_path"), TablePath);
            FieldRow->SetNumberField(TEXT("row_index"), RowIndex);
            FieldRow->SetStringField(TEXT("row_name"), RowName.ToString());
            FieldRow->SetStringField(TEXT("row_path"), RowPath);
            FieldRow->SetNumberField(TEXT("field_index"), FieldIndex);
            FieldRow->SetStringField(TEXT("field_name"), Property->GetName());
            FieldRow->SetStringField(TEXT("declaring_type"), DeclaringType ? DeclaringType->GetPathName() : FString());
            FieldRow->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
            FieldRow->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
            FieldRow->SetStringField(TEXT("value"), Value);
            FieldRow->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.DataTableFields.Write(FieldRow))
            {
                return false;
            }
            ++Counts.DataTableFields;
            ++FieldRowsForAsset;

            const int32 ReferenceBudget = FMath::Max(0, MaxStructuredRowsPerAsset - ReferenceRowsForAsset);
            if (ReferenceBudget > 0)
            {
                FReferenceContext Context;
                Context.AssetPath = TablePath;
                Context.OwnerPath = RowPath;
                Context.OwnerKind = TEXT("data_table_row");
                Context.RootProperty = Property->GetName();
                Context.MaxRows = FMath::Min(MaxReferencesPerRoot, ReferenceBudget);
                Context.Writers = &Writers;
                Context.Counts = &Counts;
                CollectReferences(Property, ValuePtr, Property->GetName(), 0, Context);
                ReferenceRowsForAsset += Context.Rows;
            }
        }
    }
    return true;
}

static bool ScanCurveTableDetails(
    UCurveTable* Table,
    const FAssetData& Asset,
    const FString& Kind,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Table)
    {
        return true;
    }

    const FString TablePath = Asset.GetSoftObjectPath().ToString();
    const ECurveTableMode Mode = Table->GetCurveTableMode();
    const FString ModeName = CurveTableModeName(Mode);

    TArray<FName> RowNames;
    Table->GetRowMap().GenerateKeyArray(RowNames);
    RowNames.Sort([](const FName& A, const FName& B)
    {
        return A.LexicalLess(B);
    });

    TSharedRef<FJsonObject> TableRow = MakeShared<FJsonObject>();
    TableRow->SetStringField(TEXT("table_path"), TablePath);
    TableRow->SetStringField(TEXT("table_kind"), Kind);
    TableRow->SetStringField(TEXT("class_path"), Table->GetClass()->GetPathName());
    TableRow->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    TableRow->SetStringField(TEXT("curve_mode"), ModeName);
    TableRow->SetNumberField(TEXT("row_count"), RowNames.Num());
    if (!Writers.CurveTables.Write(TableRow))
    {
        return false;
    }
    ++Counts.CurveTables;

    int32 KeyRowsForAsset = 0;
    const int32 RowLimit = FMath::Min(RowNames.Num(), MaxStructuredRowsPerAsset);
    for (int32 RowIndex = 0; RowIndex < RowLimit; ++RowIndex)
    {
        const FName RowName = RowNames[RowIndex];
        FRealCurve* const* Found = Table->GetRowMap().Find(RowName);
        const FRealCurve* Curve = Found ? *Found : nullptr;
        if (!Curve)
        {
            continue;
        }

        int32 KeyCount = 0;
        int32 SimpleInterpMode = -1;
        if (Mode == ECurveTableMode::RichCurves)
        {
            KeyCount = static_cast<const FRichCurve*>(Curve)->Keys.Num();
        }
        else if (Mode == ECurveTableMode::SimpleCurves)
        {
            const FSimpleCurve* Simple = static_cast<const FSimpleCurve*>(Curve);
            KeyCount = Simple->Keys.Num();
            SimpleInterpMode = static_cast<int32>(Simple->InterpMode.GetValue());
        }

        const FString RowPath = FString::Printf(TEXT("%s::curve[%s]"), *TablePath, *RowName.ToString());
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("table_path"), TablePath);
        Row->SetNumberField(TEXT("row_index"), RowIndex);
        Row->SetStringField(TEXT("row_name"), RowName.ToString());
        Row->SetStringField(TEXT("row_path"), RowPath);
        Row->SetStringField(TEXT("curve_mode"), ModeName);
        Row->SetNumberField(TEXT("key_count"), KeyCount);
        SetFiniteNumberOrNull(Row, TEXT("default_value"), Curve->DefaultValue);
        Row->SetNumberField(TEXT("pre_infinity_extrap"), static_cast<int32>(Curve->PreInfinityExtrap.GetValue()));
        Row->SetNumberField(TEXT("post_infinity_extrap"), static_cast<int32>(Curve->PostInfinityExtrap.GetValue()));
        Row->SetNumberField(TEXT("simple_interp_mode"), SimpleInterpMode);
        if (!Writers.CurveTableRows.Write(Row))
        {
            return false;
        }
        ++Counts.CurveTableRows;

        const int32 Remaining = FMath::Max(0, MaxStructuredRowsPerAsset - KeyRowsForAsset);
        const int32 EmitCount = FMath::Min(KeyCount, Remaining);
        for (int32 KeyIndex = 0; KeyIndex < EmitCount; ++KeyIndex)
        {
            TSharedRef<FJsonObject> KeyRow = MakeShared<FJsonObject>();
            KeyRow->SetStringField(TEXT("table_path"), TablePath);
            KeyRow->SetNumberField(TEXT("row_index"), RowIndex);
            KeyRow->SetStringField(TEXT("row_name"), RowName.ToString());
            KeyRow->SetStringField(TEXT("row_path"), RowPath);
            KeyRow->SetNumberField(TEXT("key_index"), KeyIndex);
            KeyRow->SetStringField(TEXT("curve_mode"), ModeName);

            if (Mode == ECurveTableMode::RichCurves)
            {
                const FRichCurveKey& Key = static_cast<const FRichCurve*>(Curve)->Keys[KeyIndex];
                SetFiniteNumberOrNull(KeyRow, TEXT("time"), Key.Time);
                SetFiniteNumberOrNull(KeyRow, TEXT("value"), Key.Value);
                KeyRow->SetNumberField(TEXT("interp_mode"), static_cast<int32>(Key.InterpMode.GetValue()));
                KeyRow->SetNumberField(TEXT("tangent_mode"), static_cast<int32>(Key.TangentMode.GetValue()));
                KeyRow->SetNumberField(TEXT("tangent_weight_mode"), static_cast<int32>(Key.TangentWeightMode.GetValue()));
                SetFiniteNumberOrNull(KeyRow, TEXT("arrive_tangent"), Key.ArriveTangent);
                SetFiniteNumberOrNull(KeyRow, TEXT("leave_tangent"), Key.LeaveTangent);
                SetFiniteNumberOrNull(KeyRow, TEXT("arrive_tangent_weight"), Key.ArriveTangentWeight);
                SetFiniteNumberOrNull(KeyRow, TEXT("leave_tangent_weight"), Key.LeaveTangentWeight);
            }
            else
            {
                const FSimpleCurveKey& Key = static_cast<const FSimpleCurve*>(Curve)->Keys[KeyIndex];
                SetFiniteNumberOrNull(KeyRow, TEXT("time"), Key.Time);
                SetFiniteNumberOrNull(KeyRow, TEXT("value"), Key.Value);
                KeyRow->SetNumberField(TEXT("interp_mode"), SimpleInterpMode);
                KeyRow->SetNumberField(TEXT("tangent_mode"), -1);
                KeyRow->SetNumberField(TEXT("tangent_weight_mode"), -1);
                KeyRow->SetNumberField(TEXT("arrive_tangent"), 0.0);
                KeyRow->SetNumberField(TEXT("leave_tangent"), 0.0);
                KeyRow->SetNumberField(TEXT("arrive_tangent_weight"), 0.0);
                KeyRow->SetNumberField(TEXT("leave_tangent_weight"), 0.0);
            }

            if (!Writers.CurveTableKeys.Write(KeyRow))
            {
                return false;
            }
            ++Counts.CurveTableKeys;
            ++KeyRowsForAsset;
        }
    }
    return true;
}

static bool ScanPrimaryDataAsset(
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

    const FPrimaryAssetId PrimaryId = Object->GetPrimaryAssetId();
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), Asset.GetSoftObjectPath().ToString());
    Row->SetStringField(TEXT("asset_kind"), Kind);
    Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetBoolField(TEXT("primary_asset_id_valid"), PrimaryId.IsValid());
    Row->SetStringField(TEXT("primary_asset_type"), PrimaryId.PrimaryAssetType.ToString());
    Row->SetStringField(TEXT("primary_asset_name"), PrimaryId.PrimaryAssetName.ToString());
    Row->SetStringField(TEXT("primary_asset_id"), PrimaryId.ToString());
    if (!Writers.PrimaryDataAssets.Write(Row))
    {
        return false;
    }
    ++Counts.PrimaryDataAssets;
    return true;
}

static bool WriteGameplayTagRedirectsForList(
    UObject* ListObject,
    const FString& SourceName,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& Seen)
{
    if (!ListObject)
    {
        return true;
    }
    const FArrayProperty* Redirects = CastField<FArrayProperty>(
        ListObject->GetClass()->FindPropertyByName(TEXT("GameplayTagRedirects")));
    const FStructProperty* RedirectStruct = Redirects ? CastField<FStructProperty>(Redirects->Inner) : nullptr;
    const void* ValuePtr = Redirects ? Redirects->ContainerPtrToValuePtr<void>(ListObject) : nullptr;
    if (!Redirects || !RedirectStruct || !RedirectStruct->Struct || !ValuePtr)
    {
        return true;
    }

    FScriptArrayHelper Helper(Redirects, ValuePtr);
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Item = Helper.GetRawPtr(Index);
        const FString OldTag = GetNameField(RedirectStruct->Struct, Item, TEXT("OldTagName"), ListObject);
        const FString NewTag = GetNameField(RedirectStruct->Struct, Item, TEXT("NewTagName"), ListObject);
        const FString Key = SourceName + TEXT("\x1f") + OldTag + TEXT("\x1f") + NewTag;
        if (OldTag.IsEmpty() || Seen.Contains(Key))
        {
            continue;
        }
        Seen.Add(Key);

        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetNumberField(TEXT("redirect_index"), Counts.GameplayTagRedirects);
        Row->SetStringField(TEXT("source_name"), SourceName);
        Row->SetStringField(TEXT("old_tag"), OldTag);
        Row->SetStringField(TEXT("new_tag"), NewTag);
        if (!Writers.GameplayTagRedirects.Write(Row))
        {
            return false;
        }
        ++Counts.GameplayTagRedirects;
    }
    return true;
}

static bool ScanGameplayTagProjectModel(FWriters& Writers, FCounts& Counts)
{
    const UGameplayTagsSettings* Settings = GetDefault<UGameplayTagsSettings>();
    if (!Settings)
    {
        return true;
    }

    TSharedRef<FJsonObject> SettingsRow = MakeShared<FJsonObject>();
    SettingsRow->SetStringField(TEXT("settings_path"), Settings->GetPathName());
    SettingsRow->SetStringField(TEXT("class_path"), Settings->GetClass()->GetPathName());
    SettingsRow->SetStringField(TEXT("config_file_name"), Settings->ConfigFileName);
    SettingsRow->SetStringField(TEXT("import_tags_from_config"), ExportField(const_cast<UGameplayTagsSettings*>(Settings), TEXT("ImportTagsFromConfig")));
    SettingsRow->SetStringField(TEXT("warn_on_invalid_tags"), ExportField(const_cast<UGameplayTagsSettings*>(Settings), TEXT("WarnOnInvalidTags")));
    SettingsRow->SetStringField(TEXT("fast_replication"), ExportFirstField(const_cast<UGameplayTagsSettings*>(Settings), {TEXT("FastReplication"), TEXT("bFastReplication")}));
    SettingsRow->SetStringField(TEXT("invalid_tag_characters"), Settings->InvalidTagCharacters);
    SettingsRow->SetStringField(TEXT("gameplay_tag_table_list"), ExportField(const_cast<UGameplayTagsSettings*>(Settings), TEXT("GameplayTagTableList")));
    SettingsRow->SetStringField(TEXT("restricted_config_files"), ExportField(const_cast<UGameplayTagsSettings*>(Settings), TEXT("RestrictedConfigFiles")));
    SettingsRow->SetNumberField(TEXT("num_bits_for_container_size"), Settings->NumBitsForContainerSize);
    SettingsRow->SetNumberField(TEXT("net_index_first_bit_segment"), Settings->NetIndexFirstBitSegment);
    if (!Writers.GameplayTagSettings.Write(SettingsRow))
    {
        return false;
    }
    ++Counts.GameplayTagSettings;

    UGameplayTagsManager& Manager = UGameplayTagsManager::Get();
    TSet<FString> SeenRedirects;
    int32 SourceIndex = 0;
    const EGameplayTagSourceType SourceTypes[] = {
        EGameplayTagSourceType::Native,
        EGameplayTagSourceType::DefaultTagList,
        EGameplayTagSourceType::TagList,
        EGameplayTagSourceType::RestrictedTagList,
        EGameplayTagSourceType::DataTable,
    };
    for (const EGameplayTagSourceType SourceType : SourceTypes)
    {
        TArray<const FGameplayTagSource*> Sources;
        Manager.FindTagSourcesWithType(SourceType, Sources);
        Sources.Sort([](const FGameplayTagSource& A, const FGameplayTagSource& B)
        {
            return A.SourceName.LexicalLess(B.SourceName);
        });
        for (const FGameplayTagSource* Source : Sources)
        {
            if (!Source)
            {
                continue;
            }
            TArray<TSharedPtr<FGameplayTagNode>> SourceTags;
            Manager.GetAllTagsFromSource(Source->SourceName, SourceTags);
            TArray<FString> Owners;
            Manager.GetOwnersForTagSource(Source->SourceName.ToString(), Owners);
            Owners.Sort();

            TSharedRef<FJsonObject> SourceRow = MakeShared<FJsonObject>();
            SourceRow->SetNumberField(TEXT("source_index"), SourceIndex++);
            SourceRow->SetStringField(TEXT("source_name"), Source->SourceName.ToString());
            SourceRow->SetStringField(TEXT("source_type"), GameplayTagSourceTypeName(Source->SourceType));
            SourceRow->SetStringField(TEXT("config_file"), Source->GetConfigFileName());
            SourceRow->SetStringField(TEXT("source_tag_list_path"), Source->SourceTagList ? Source->SourceTagList->GetPathName() : FString());
            SourceRow->SetStringField(TEXT("source_restricted_tag_list_path"), Source->SourceRestrictedTagList ? Source->SourceRestrictedTagList->GetPathName() : FString());
            SourceRow->SetNumberField(TEXT("tag_count"), SourceTags.Num());
            TArray<TSharedPtr<FJsonValue>> OwnerValues;
            for (const FString& Owner : Owners)
            {
                OwnerValues.Add(MakeShared<FJsonValueString>(Owner));
            }
            SourceRow->SetArrayField(TEXT("owners"), OwnerValues);
            if (!Writers.GameplayTagSources.Write(SourceRow))
            {
                return false;
            }
            ++Counts.GameplayTagSources;

            if (!WriteGameplayTagRedirectsForList(
                Source->SourceTagList,
                Source->SourceName.ToString(),
                Writers,
                Counts,
                SeenRedirects))
            {
                return false;
            }
        }
    }

    FGameplayTagContainer DictionaryContainer;
    Manager.RequestAllGameplayTags(DictionaryContainer, true);
    TArray<FGameplayTag> Tags;
    DictionaryContainer.GetGameplayTagArray(Tags);
    Tags.Sort([](const FGameplayTag& A, const FGameplayTag& B)
    {
        return A.GetTagName().LexicalLess(B.GetTagName());
    });

    for (int32 TagIndex = 0; TagIndex < Tags.Num(); ++TagIndex)
    {
        const FGameplayTag& Tag = Tags[TagIndex];
        const FName TagName = Tag.GetTagName();
        FString Comment;
        TArray<FName> SourceNames;
        bool bExplicit = false;
        bool bRestricted = false;
        bool bAllowNonRestrictedChildren = false;
        Manager.GetTagEditorData(
            TagName,
            Comment,
            SourceNames,
            bExplicit,
            bRestricted,
            bAllowNonRestrictedChildren);
        SourceNames.Sort(FNameLexicalLess());

        const FGameplayTag Parent = Manager.RequestGameplayTagDirectParent(Tag);
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetNumberField(TEXT("tag_index"), TagIndex);
        Row->SetStringField(TEXT("tag"), TagName.ToString());
        Row->SetStringField(TEXT("parent_tag"), Parent.IsValid() ? Parent.ToString() : FString());
        Row->SetStringField(TEXT("comment"), Comment);
        Row->SetBoolField(TEXT("explicit"), bExplicit);
        Row->SetBoolField(TEXT("restricted"), bRestricted);
        Row->SetBoolField(TEXT("allow_non_restricted_children"), bAllowNonRestrictedChildren);
        Row->SetNumberField(TEXT("depth"), Manager.GetNumberOfTagNodes(Tag));
        TArray<TSharedPtr<FJsonValue>> SourceValues;
        for (const FName SourceName : SourceNames)
        {
            SourceValues.Add(MakeShared<FJsonValueString>(SourceName.ToString()));
        }
        Row->SetArrayField(TEXT("sources"), SourceValues);
        if (!Writers.GameplayTagDictionary.Write(Row))
        {
            return false;
        }
        ++Counts.GameplayTagDictionary;
    }
    return true;
}
