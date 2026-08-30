static bool ScanNiagaraScript(
    UObject* Object,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts)
{
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("script_path"), Asset.GetSoftObjectPath().ToString());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("usage"), ExportField(Object, TEXT("Usage")));
    Row->SetStringField(TEXT("usage_id"), ExportField(Object, TEXT("UsageId")));
    Row->SetStringField(TEXT("exposed_version"), ExportField(Object, TEXT("ExposedVersion")));
    Row->SetNumberField(TEXT("version_count"), CountArray(Object->GetClass(), Object, TEXT("VersionData")));
    if (!Writers.NiagaraScripts.Write(Row))
    {
        return false;
    }
    ++Counts.NiagaraScripts;
    return true;
}

static bool ScanNiagaraDataChannel(
    UObject* Object,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    UObject* DataChannel = GetObjectField(Object, TEXT("DataChannel"));
    int32 VariableCount = 0;

    if (DataChannel)
    {
        // UE 5.8 uses ChannelVariables. Keep Variables as a reflection fallback
        // for older/custom Niagara implementations without hard-linking Niagara.
        FArrayProperty* Variables = FindArrayField(
            DataChannel->GetClass(),
            TEXT("ChannelVariables"),
            TEXT("Variables"));
        const FStructProperty* VariableStruct = Variables
            ? CastField<FStructProperty>(Variables->Inner)
            : nullptr;
        const void* ValuePtr = Variables
            ? Variables->ContainerPtrToValuePtr<void>(DataChannel)
            : nullptr;

        if (Variables && VariableStruct && ValuePtr)
        {
            FScriptArrayHelper Helper(Variables, ValuePtr);
            VariableCount = Helper.Num();

            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                const void* Variable = Helper.GetRawPtr(Index);
                FString Type = ExportField(
                    VariableStruct->Struct,
                    Variable,
                    TEXT("TypeDef"),
                    DataChannel);
                if (Type.IsEmpty())
                {
                    Type = ExportField(
                        VariableStruct->Struct,
                        Variable,
                        TEXT("TypeDefHandle"),
                        DataChannel);
                }

                bool bTruncated = false;
                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("data_channel_path"), AssetPath);
                Row->SetNumberField(TEXT("variable_index"), Index);
                Row->SetStringField(TEXT("version"), ExportField(
                    VariableStruct->Struct,
                    Variable,
                    TEXT("Version"),
                    DataChannel));
                Row->SetStringField(TEXT("name"), GetNameField(
                    VariableStruct->Struct,
                    Variable,
                    TEXT("Name"),
                    DataChannel));
                Row->SetStringField(TEXT("type"), Type);
                Row->SetStringField(
                    TEXT("raw_value"),
                    ExportProperty(Variables->Inner, Variable, DataChannel, bTruncated));
                Row->SetBoolField(TEXT("truncated"), bTruncated);
                if (!Writers.NiagaraDataChannelVariables.Write(Row))
                {
                    return false;
                }
                ++Counts.NiagaraDataChannelVariables;
            }
        }

        if (!WriteObjectState(
            DataChannel,
            AssetPath,
            TEXT("niagara_data_channel_definition"),
            Writers,
            Counts,
            SeenStateOwners))
        {
            return false;
        }
    }

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("data_channel_path"), AssetPath);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("definition_path"), DataChannel ? DataChannel->GetPathName() : FString());
    Summary->SetStringField(TEXT("definition_class"), DataChannel ? DataChannel->GetClass()->GetPathName() : FString());
    Summary->SetNumberField(TEXT("variable_count"), VariableCount);
    if (!Writers.NiagaraDataChannels.Write(Summary))
    {
        return false;
    }
    ++Counts.NiagaraDataChannels;
    return true;
}

static bool ScanNiagaraParameterCollection(
    UObject* Object,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    FArrayProperty* Parameters = FindArrayField(Object->GetClass(), TEXT("Parameters"));
    const FStructProperty* ParameterStruct = Parameters
        ? CastField<FStructProperty>(Parameters->Inner)
        : nullptr;
    const void* ValuePtr = Parameters
        ? Parameters->ContainerPtrToValuePtr<void>(Object)
        : nullptr;

    int32 ParameterCount = 0;
    if (Parameters && ParameterStruct && ValuePtr)
    {
        FScriptArrayHelper Helper(Parameters, ValuePtr);
        ParameterCount = Helper.Num();

        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Parameter = Helper.GetRawPtr(Index);
            FString Type = ExportField(
                ParameterStruct->Struct,
                Parameter,
                TEXT("TypeDef"),
                Object);
            if (Type.IsEmpty())
            {
                Type = ExportField(
                    ParameterStruct->Struct,
                    Parameter,
                    TEXT("TypeDefHandle"),
                    Object);
            }

            bool bTruncated = false;
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("collection_path"), AssetPath);
            Row->SetNumberField(TEXT("parameter_index"), Index);
            Row->SetStringField(TEXT("name"), GetNameField(
                ParameterStruct->Struct,
                Parameter,
                TEXT("Name"),
                Object));
            Row->SetStringField(TEXT("type"), Type);
            Row->SetStringField(
                TEXT("raw_value"),
                ExportProperty(Parameters->Inner, Parameter, Object, bTruncated));
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.NiagaraParameterCollectionParameters.Write(Row))
            {
                return false;
            }
            ++Counts.NiagaraParameterCollectionParameters;
        }
    }

    UObject* SourceCollection = GetObjectField(Object, TEXT("SourceMaterialCollection"));
    if (!SourceCollection)
    {
        SourceCollection = GetObjectField(Object, TEXT("SourceCollection"));
    }
    UObject* DefaultInstance = GetObjectField(Object, TEXT("DefaultInstance"));

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("collection_path"), AssetPath);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetStringField(TEXT("namespace"), ExportField(Object, TEXT("Namespace")));
    Summary->SetNumberField(TEXT("parameter_count"), ParameterCount);
    Summary->SetStringField(TEXT("source_collection_path"), SourceCollection ? SourceCollection->GetPathName() : FString());
    Summary->SetStringField(TEXT("source_collection_class"), SourceCollection ? SourceCollection->GetClass()->GetPathName() : FString());
    Summary->SetStringField(TEXT("default_instance_path"), DefaultInstance ? DefaultInstance->GetPathName() : FString());
    Summary->SetStringField(TEXT("default_instance_class"), DefaultInstance ? DefaultInstance->GetClass()->GetPathName() : FString());
    if (!Writers.NiagaraParameterCollections.Write(Summary))
    {
        return false;
    }
    ++Counts.NiagaraParameterCollections;

    if (DefaultInstance && !WriteObjectState(
        DefaultInstance,
        AssetPath,
        TEXT("niagara_parameter_collection_default_instance"),
        Writers,
        Counts,
        SeenStateOwners))
    {
        return false;
    }

    return true;
}
