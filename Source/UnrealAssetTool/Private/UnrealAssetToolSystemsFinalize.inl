static bool GSystemsOnlyWriterBuffersFinalized = false;

static void FinalizeSystemsOnlyWriterBuffers()
{
    if (!FParse::Param(FCommandLine::Get(), TEXT("UnrealAssetToolSystemsOnly")) ||
        GSystemsOnlyWriterBuffersFinalized)
    {
        return;
    }

    // The schema-3/4/5 writer groups are static because their extraction
    // helpers are spread across included implementation files. Systems-only
    // mode requests exit immediately after RunSystemsScan() returns. Do not
    // depend on a later OnPostEngineInit callback continuing to run after that
    // exit request: finalize during the engine's explicit pre-exit phase,
    // before modules and their static storage begin shutting down.
    GMoverWriters = FMoverWriters();
    GGameplayCameraWriters = FGameplayCameraWriters();
    GMassZoneGraphWriters = FMassZoneGraphWriters();
    GSystemsOnlyWriterBuffersFinalized = true;

    UE_LOG(LogTemp, Display, TEXT("UnrealAssetToolSystems: finalized specialized JSONL writer buffers before engine exit"));
}

struct FSystemsFinalizeBootstrap
{
    FSystemsFinalizeBootstrap()
    {
        FCoreDelegates::OnEnginePreExit.AddStatic(&FinalizeSystemsOnlyWriterBuffers);
    }
};

static FSystemsFinalizeBootstrap GSystemsFinalizeBootstrap;
