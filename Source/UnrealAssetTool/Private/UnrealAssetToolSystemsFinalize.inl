static void FinalizeSystemsOnlyWriterBuffers()
{
    if (!FParse::Param(FCommandLine::Get(), TEXT("UnrealAssetToolSystemsOnly")))
    {
        return;
    }

    // The schema-3/4/5 writer groups are static because their extraction
    // helpers are spread across included implementation files. A normal full
    // commandlet run keeps the process alive long enough for their archives to
    // be finalized during module shutdown, but systems-only mode requests exit
    // immediately after RunSystemsScan() returns. Explicitly replace the writer
    // groups here, after the systems callback has completed, so every FArchive
    // is destroyed/flushed before the editor observes the exit request.
    GMoverWriters = FMoverWriters();
    GGameplayCameraWriters = FGameplayCameraWriters();
    GMassZoneGraphWriters = FMassZoneGraphWriters();

    UE_LOG(LogTemp, Display, TEXT("UnrealAssetToolSystems: finalized specialized JSONL writer buffers"));
}

struct FSystemsFinalizeBootstrap
{
    FSystemsFinalizeBootstrap()
    {
        // This bootstrap is defined after the main systems driver bootstrap in
        // this translation unit, so its callback is registered afterward. The
        // main callback runs the scan and calls RequestExit(); Broadcast then
        // continues here and closes the specialized writers before shutdown.
        FCoreDelegates::GetOnPostEngineInit().AddStatic(&FinalizeSystemsOnlyWriterBuffers);
    }
};

static FSystemsFinalizeBootstrap GSystemsFinalizeBootstrap;
