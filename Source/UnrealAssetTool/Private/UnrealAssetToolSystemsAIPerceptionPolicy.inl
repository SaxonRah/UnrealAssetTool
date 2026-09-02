static bool ScanGASSmartObjectsAndAIPerceptionProjectModels(
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
    GAIPerceptionCounts = FAIPerceptionCounts();

    const FString OutputDir = SmartObjectSystemsOutputDir();
    if (!GAIPerceptionWriters.Open(OutputDir))
    {
        OutError = TEXT("could not create AI Perception systems JSONL output files");
        GAIPerceptionWriters = FAIPerceptionWriters();
        return false;
    }

    const bool bAIPerceptionOk = ScanAIPerceptionProjectModel(
        Assets,
        ProjectDir,
        bIncludeEngine,
        bIncludeSelf,
        ToolPluginDir,
        OutError);

    // These specialist streams are separate from the legacy driver writer group.
    // Destroy the writers synchronously before the authoritative manifest write.
    GAIPerceptionWriters = FAIPerceptionWriters();
    if (!bAIPerceptionOk)
    {
        return false;
    }

    return ScanGASAndSmartObjectProjectModels(
        Assets,
        ProjectDir,
        bIncludeEngine,
        bIncludeSelf,
        ToolPluginDir,
        Writers,
        Counts,
        SeenStateOwners,
        OutError);
}

static bool UpgradeSystemsManifestToSchema8(const FString& ManifestPath)
{
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *ManifestPath))
    {
        return false;
    }

    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        return false;
    }

    Root->SetNumberField(TEXT("schema_version"), 8);

    TSharedPtr<FJsonObject> Counts;
    const TSharedPtr<FJsonObject>* CountsField = nullptr;
    if (Root->TryGetObjectField(TEXT("counts"), CountsField) && CountsField && CountsField->IsValid())
    {
        Counts = *CountsField;
    }
    else
    {
        Counts = MakeShared<FJsonObject>();
        Root->SetObjectField(TEXT("counts"), Counts.ToSharedRef());
    }
    Counts->SetNumberField(TEXT("ai_perception_components"), GAIPerceptionCounts.Components);
    Counts->SetNumberField(TEXT("ai_perception_sense_configs"), GAIPerceptionCounts.SenseConfigs);
    Counts->SetNumberField(TEXT("ai_perception_stimuli_sources"), GAIPerceptionCounts.StimuliSources);
    Counts->SetNumberField(TEXT("ai_perception_registered_senses"), GAIPerceptionCounts.RegisteredSenses);
    Counts->SetNumberField(TEXT("ai_perception_properties"), GAIPerceptionCounts.Properties);

    TArray<TSharedPtr<FJsonValue>> Files;
    const TArray<TSharedPtr<FJsonValue>>* ExistingFiles = nullptr;
    if (Root->TryGetArrayField(TEXT("files"), ExistingFiles) && ExistingFiles)
    {
        Files = *ExistingFiles;
    }
    TSet<FString> ExistingNames;
    for (const TSharedPtr<FJsonValue>& Value : Files)
    {
        FString Name;
        if (Value.IsValid() && Value->TryGetString(Name))
        {
            ExistingNames.Add(Name);
        }
    }
    static const TCHAR* AIPerceptionFiles[] = {
        TEXT("ai_perception_components.jsonl"),
        TEXT("ai_perception_sense_configs.jsonl"),
        TEXT("ai_perception_stimuli_sources.jsonl"),
        TEXT("ai_perception_registered_senses.jsonl"),
        TEXT("ai_perception_properties.jsonl")
    };
    for (const TCHAR* Name : AIPerceptionFiles)
    {
        if (!ExistingNames.Contains(Name))
        {
            Files.Add(MakeShared<FJsonValueString>(Name));
        }
    }
    Root->SetArrayField(TEXT("files"), Files);

    FString Updated;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Updated);
    if (!FJsonSerializer::Serialize(Root.ToSharedRef(), Writer))
    {
        return false;
    }
    if (!FFileHelper::SaveStringToFile(
            Updated,
            *ManifestPath,
            FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
    {
        return false;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolSystems: synchronously promoted systems manifest to schema 8 ai_perception components=%lld configs=%lld stimuli_sources=%lld registered_senses=%lld properties=%lld"),
        GAIPerceptionCounts.Components,
        GAIPerceptionCounts.SenseConfigs,
        GAIPerceptionCounts.StimuliSources,
        GAIPerceptionCounts.RegisteredSenses,
        GAIPerceptionCounts.Properties);
    return true;
}

struct FAIPerceptionSystemsFileHelperProxy
{
    using EEncodingOptions = FFileHelper::EEncodingOptions;

    static bool SaveStringToFile(
        const FString& String,
        const TCHAR* Filename,
        EEncodingOptions EncodingOptions)
    {
        if (!FSmartObjectSystemsFileHelperProxy::SaveStringToFile(String, Filename, EncodingOptions))
        {
            return false;
        }

        const FString Path = Filename ? FString(Filename) : FString();
        if (!FPaths::GetCleanFilename(Path).Equals(TEXT("systems_manifest.json"), ESearchCase::IgnoreCase))
        {
            return true;
        }
        return UpgradeSystemsManifestToSchema8(Path);
    }
};
