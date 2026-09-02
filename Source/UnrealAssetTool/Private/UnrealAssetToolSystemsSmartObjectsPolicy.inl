static bool GSmartObjectSchema7ScanAttempted = false;
static bool GSmartObjectSchema7ExitHookRegistered = false;

static void FinalizeSmartObjectSchema7Manifest();

static FString SmartObjectSystemsOutputDir()
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
    return NormalizeAbsolutePath(OutputDir);
}

static bool ScanGASAndSmartObjectProjectModels(
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
    GSmartObjectSchema7ScanAttempted = true;
    GSmartObjectCounts = FSmartObjectCounts();

    // Register shutdown work only after the engine is initialized. UE 5.8
    // tightened delegate initialization ordering, and translation-unit static
    // registration can be lost before the engine loop owns these delegates.
    if (!GSmartObjectSchema7ExitHookRegistered)
    {
        FCoreDelegates::OnEnginePreExit.AddStatic(&FinalizeSmartObjectSchema7Manifest);
        FCoreDelegates::OnPreExit.AddStatic(&FinalizeSmartObjectSchema7Manifest);
        FCoreDelegates::OnExit.AddStatic(&FinalizeSmartObjectSchema7Manifest);
        GSmartObjectSchema7ExitHookRegistered = true;
    }

    const FString OutputDir = SmartObjectSystemsOutputDir();
    if (!GSmartObjectWriters.Open(OutputDir))
    {
        OutError = TEXT("could not create Smart Object systems JSONL output files");
        GSmartObjectWriters = FSmartObjectWriters();
        return false;
    }

    const bool bSmartObjectsOk = ScanSmartObjectProjectModel(
        Assets,
        ProjectDir,
        bIncludeEngine,
        bIncludeSelf,
        ToolPluginDir,
        Writers,
        Counts,
        SeenStateOwners,
        OutError);

    // Smart Object streams are not owned by the legacy driver writer group.
    // Finalize them synchronously before the driver publishes its manifest.
    GSmartObjectWriters = FSmartObjectWriters();
    if (!bSmartObjectsOk)
    {
        return false;
    }

    return ScanGASProjectModelPolicy(
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

static bool UpgradeSystemsManifestToSchema7()
{
    if (!GSmartObjectSchema7ScanAttempted)
    {
        return true;
    }

    const FString OutputDir = SmartObjectSystemsOutputDir();
    const FString ManifestPath = FPaths::Combine(OutputDir, TEXT("systems_manifest.json"));
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

    Root->SetNumberField(TEXT("schema_version"), 7);

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
    Counts->SetNumberField(TEXT("smartobject_definitions"), GSmartObjectCounts.Definitions);
    Counts->SetNumberField(TEXT("smartobject_slots"), GSmartObjectCounts.Slots);
    Counts->SetNumberField(TEXT("smartobject_behaviors"), GSmartObjectCounts.Behaviors);
    Counts->SetNumberField(TEXT("smartobject_behavior_properties"), GSmartObjectCounts.BehaviorProperties);

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
    static const TCHAR* SmartObjectFiles[] = {
        TEXT("smartobject_definitions.jsonl"),
        TEXT("smartobject_slots.jsonl"),
        TEXT("smartobject_behaviors.jsonl"),
        TEXT("smartobject_behavior_properties.jsonl")
    };
    for (const TCHAR* Name : SmartObjectFiles)
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
        TEXT("UnrealAssetToolSystems: promoted systems manifest to schema 7 smartobjects definitions=%lld slots=%lld behaviors=%lld behavior_properties=%lld"),
        GSmartObjectCounts.Definitions,
        GSmartObjectCounts.Slots,
        GSmartObjectCounts.Behaviors,
        GSmartObjectCounts.BehaviorProperties);
    return true;
}

static void FinalizeSmartObjectSchema7Manifest()
{
    static bool bFinalized = false;
    if (bFinalized)
    {
        return;
    }
    if (UpgradeSystemsManifestToSchema7())
    {
        bFinalized = true;
        return;
    }
    UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolSystems: failed promoting systems_manifest.json to schema 7"));
}
