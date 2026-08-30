static bool SaveManifest(
    const FString& OutputDir,
    const FCounts& Counts,
    bool bSuccess,
    const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), VFXSchemaVersion);
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolVFX"));
    Root->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);

    TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
    C->SetNumberField(TEXT("vfx_assets"), Counts.Assets);
    C->SetNumberField(TEXT("vfx_properties"), Counts.Properties);
    C->SetNumberField(TEXT("vfx_references"), Counts.References);
    C->SetNumberField(TEXT("niagara_systems"), Counts.NiagaraSystems);
    C->SetNumberField(TEXT("niagara_system_emitters"), Counts.NiagaraSystemEmitters);
    C->SetNumberField(TEXT("niagara_emitters"), Counts.NiagaraEmitters);
    C->SetNumberField(TEXT("niagara_emitter_versions"), Counts.NiagaraEmitterVersions);
    C->SetNumberField(TEXT("niagara_renderers"), Counts.NiagaraRenderers);
    C->SetNumberField(TEXT("niagara_simulation_stages"), Counts.NiagaraSimulationStages);
    C->SetNumberField(TEXT("niagara_stateless_emitters"), Counts.NiagaraStatelessEmitters);
    C->SetNumberField(TEXT("niagara_stateless_modules"), Counts.NiagaraStatelessModules);
    C->SetNumberField(TEXT("niagara_stateless_renderers"), Counts.NiagaraStatelessRenderers);
    C->SetNumberField(TEXT("niagara_scripts"), Counts.NiagaraScripts);
    C->SetNumberField(TEXT("niagara_data_channels"), Counts.NiagaraDataChannels);
    C->SetNumberField(TEXT("niagara_data_channel_variables"), Counts.NiagaraDataChannelVariables);
    C->SetNumberField(TEXT("niagara_parameter_collections"), Counts.NiagaraParameterCollections);
    C->SetNumberField(TEXT("niagara_parameter_collection_parameters"), Counts.NiagaraParameterCollectionParameters);
    C->SetNumberField(TEXT("niagara_effect_types"), Counts.NiagaraEffectTypes);
    C->SetNumberField(TEXT("cascade_systems"), Counts.CascadeSystems);
    C->SetNumberField(TEXT("cascade_emitters"), Counts.CascadeEmitters);
    C->SetNumberField(TEXT("cascade_lods"), Counts.CascadeLODs);
    C->SetNumberField(TEXT("cascade_modules"), Counts.CascadeModules);
    Root->SetObjectField(TEXT("counts"), C);

    static const TCHAR* Names[] = {
        TEXT("vfx_assets.jsonl"),
        TEXT("vfx_properties.jsonl"),
        TEXT("vfx_references.jsonl"),
        TEXT("niagara_systems.jsonl"),
        TEXT("niagara_system_emitters.jsonl"),
        TEXT("niagara_emitters.jsonl"),
        TEXT("niagara_emitter_versions.jsonl"),
        TEXT("niagara_renderers.jsonl"),
        TEXT("niagara_simulation_stages.jsonl"),
        TEXT("niagara_stateless_emitters.jsonl"),
        TEXT("niagara_stateless_modules.jsonl"),
        TEXT("niagara_stateless_renderers.jsonl"),
        TEXT("niagara_scripts.jsonl"),
        TEXT("niagara_data_channels.jsonl"),
        TEXT("niagara_data_channel_variables.jsonl"),
        TEXT("niagara_parameter_collections.jsonl"),
        TEXT("niagara_parameter_collection_parameters.jsonl"),
        TEXT("niagara_effect_types.jsonl"),
        TEXT("cascade_systems.jsonl"),
        TEXT("cascade_emitters.jsonl"),
        TEXT("cascade_lods.jsonl"),
        TEXT("cascade_modules.jsonl")
    };

    TArray<TSharedPtr<FJsonValue>> Files;
    for (const TCHAR* Name : Names)
    {
        Files.Add(MakeShared<FJsonValueString>(Name));
    }
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer))
    {
        return false;
    }

    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("vfx_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunVFXScan(FString& OutError)
{
    FString OutputDir;
    FParse::Value(FCommandLine::Get(), TEXT("Output="), OutputDir);

    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    if (OutputDir.IsEmpty())
    {
        OutputDir = FPaths::Combine(ProjectDir, TEXT(".uatool"));
    }
    else if (FPaths::IsRelative(OutputDir))
    {
        OutputDir = FPaths::Combine(ProjectDir, OutputDir);
    }
    OutputDir = NormalizeAbsolutePath(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    const bool bIncludeEngine = FParse::Param(FCommandLine::Get(), TEXT("IncludeEngine"));
    const bool bIncludeSelf = FParse::Param(FCommandLine::Get(), TEXT("IncludeSelf"));

    FString ToolPluginDir;
    if (const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("UnrealAssetTool")); Plugin.IsValid())
    {
        ToolPluginDir = NormalizeAbsolutePath(Plugin->GetBaseDir());
    }

    FWriters Writers;
    FCounts Counts;
    if (!Writers.Open(OutputDir))
    {
        OutError = TEXT("could not create VFX JSONL output files");
        SaveManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.SearchAllAssets(true);

    TArray<FAssetData> Assets;
    Registry.GetAllAssets(Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString();
    });

    TSet<FString> SeenNiagaraEmitters;
    TSet<FString> SeenStatelessEmitters;
    TSet<FString> SeenStateOwners;

    for (const FAssetData& Asset : Assets)
    {
        const FString Kind = KindForClass(Asset.AssetClassPath.ToString());
        if (Kind.IsEmpty())
        {
            continue;
        }

        FString PackageFilename;
        const bool bHasDiskPackage = FPackageName::DoesPackageExist(
            Asset.PackageName.ToString(),
            &PackageFilename,
            false);

        if (!bIncludeSelf &&
            bHasDiskPackage &&
            !ToolPluginDir.IsEmpty() &&
            IsInsideDirectory(PackageFilename, ToolPluginDir))
        {
            continue;
        }

        if (!bIncludeEngine &&
            (!bHasDiskPackage || !IsInsideDirectory(PackageFilename, ProjectDir)))
        {
            continue;
        }

        UObject* Object = Asset.GetAsset();
        if (!Object)
        {
            continue;
        }

        const FString AssetPath = Asset.GetSoftObjectPath().ToString();

        TSharedRef<FJsonObject> AssetRow = MakeShared<FJsonObject>();
        AssetRow->SetStringField(TEXT("vfx_path"), AssetPath);
        AssetRow->SetStringField(TEXT("vfx_kind"), Kind);
        AssetRow->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
        AssetRow->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
        AssetRow->SetStringField(
            TEXT("family"),
            Kind.StartsWith(TEXT("niagara_")) ? TEXT("niagara") : TEXT("cascade"));
        if (!Writers.Assets.Write(AssetRow))
        {
            OutError = TEXT("failed writing VFX asset ") + AssetPath;
            SaveManifest(OutputDir, Counts, false, OutError);
            return false;
        }
        ++Counts.Assets;

        if (!WriteObjectState(
            Object,
            AssetPath,
            Kind,
            Writers,
            Counts,
            SeenStateOwners))
        {
            OutError = TEXT("failed writing VFX state for ") + AssetPath;
            SaveManifest(OutputDir, Counts, false, OutError);
            return false;
        }

        bool bOk = true;
        if (Kind == TEXT("niagara_system"))
        {
            bOk = ScanNiagaraSystem(
                Object,
                Asset,
                Writers,
                Counts,
                SeenNiagaraEmitters,
                SeenStatelessEmitters,
                SeenStateOwners);
        }
        else if (Kind == TEXT("niagara_emitter"))
        {
            bOk = WriteNiagaraEmitterObject(
                Object,
                AssetPath,
                Writers,
                Counts,
                SeenNiagaraEmitters,
                SeenStateOwners);
        }
        else if (Kind == TEXT("niagara_stateless_emitter"))
        {
            bOk = WriteNiagaraStatelessEmitterObject(
                Object,
                AssetPath,
                Writers,
                Counts,
                SeenStatelessEmitters,
                SeenStateOwners);
        }
        else if (Kind == TEXT("niagara_script"))
        {
            bOk = ScanNiagaraScript(Object, Asset, Writers, Counts);
        }
        else if (Kind == TEXT("niagara_data_channel"))
        {
            bOk = ScanNiagaraDataChannel(
                Object,
                Asset,
                Writers,
                Counts,
                SeenStateOwners);
        }
        else if (Kind == TEXT("niagara_parameter_collection"))
        {
            bOk = ScanNiagaraParameterCollection(
                Object,
                Asset,
                Writers,
                Counts,
                SeenStateOwners);
        }
        else if (Kind == TEXT("niagara_effect_type"))
        {
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("effect_type_path"), AssetPath);
            Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
            Row->SetStringField(TEXT("update_frequency"), ExportField(Object, TEXT("UpdateFrequency")));
            Row->SetStringField(TEXT("cull_reaction"), ExportField(Object, TEXT("CullReaction")));
            bOk = Writers.NiagaraEffectTypes.Write(Row);
            if (bOk)
            {
                ++Counts.NiagaraEffectTypes;
            }
        }
        else if (Kind == TEXT("cascade_particle_system"))
        {
            bOk = ScanCascadeSystem(
                Object,
                Asset,
                Writers,
                Counts,
                SeenStateOwners);
        }

        if (!bOk)
        {
            OutError = TEXT("failed while scanning VFX asset ") + AssetPath;
            SaveManifest(OutputDir, Counts, false, OutError);
            return false;
        }
    }

    if (!SaveManifest(OutputDir, Counts, true, FString()))
    {
        OutError = TEXT("could not write vfx_manifest.json");
        return false;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolVFX: assets=%lld systems=%lld system_emitters=%lld emitters=%lld stateless_emitters=%lld renderers=%lld stateless_renderers=%lld data_channel_variables=%lld parameter_collections=%lld cascade_systems=%lld cascade_modules=%lld"),
        Counts.Assets,
        Counts.NiagaraSystems,
        Counts.NiagaraSystemEmitters,
        Counts.NiagaraEmitters,
        Counts.NiagaraStatelessEmitters,
        Counts.NiagaraRenderers,
        Counts.NiagaraStatelessRenderers,
        Counts.NiagaraDataChannelVariables,
        Counts.NiagaraParameterCollections,
        Counts.CascadeSystems,
        Counts.CascadeModules);

    return true;
}

static void OnPostEngineInit()
{
    FString RunCommandlet;
    FParse::Value(FCommandLine::Get(), TEXT("run="), RunCommandlet);
    if (!RunCommandlet.Equals(TEXT("UnrealAssetToolWorld"), ESearchCase::IgnoreCase))
    {
        return;
    }

    FString Error;
    if (!RunVFXScan(Error))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolVFX: %s"), *Error);
    }
}

struct FVFXScannerBootstrap
{
    FVFXScannerBootstrap()
    {
        FCoreDelegates::GetOnPostEngineInit().AddStatic(&OnPostEngineInit);
    }
};

static FVFXScannerBootstrap GVFXScannerBootstrap;
