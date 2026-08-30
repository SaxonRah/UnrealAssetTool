static bool WriteNiagaraEmitterObject(
    UObject* Emitter,
    const FString& AssetPath,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenEmitters,
    TSet<FString>& SeenStateOwners)
{
    if (!Emitter)
    {
        return true;
    }

    const FString EmitterPath = Emitter->GetPathName();
    if (SeenEmitters.Contains(EmitterPath))
    {
        return true;
    }
    SeenEmitters.Add(EmitterPath);

    FArrayProperty* VersionData = CastField<FArrayProperty>(
        Emitter->GetClass()->FindPropertyByName(TEXT("VersionData")));
    const FStructProperty* VersionStruct = VersionData
        ? CastField<FStructProperty>(VersionData->Inner)
        : nullptr;
    const void* VersionArrayValue = VersionData
        ? VersionData->ContainerPtrToValuePtr<void>(Emitter)
        : nullptr;

    int32 VersionCount = 0;
    if (VersionData && VersionStruct && VersionArrayValue)
    {
        FScriptArrayHelper Versions(VersionData, VersionArrayValue);
        VersionCount = Versions.Num();

        for (int32 VersionIndex = 0; VersionIndex < Versions.Num(); ++VersionIndex)
        {
            const void* VersionValue = Versions.GetRawPtr(VersionIndex);
            const FString VersionRaw = ExportField(VersionStruct->Struct, VersionValue, TEXT("Version"), Emitter);
            const FString SimTarget = ExportField(VersionStruct->Struct, VersionValue, TEXT("SimTarget"), Emitter);
            const FString CalculateBoundsMode = ExportField(
                VersionStruct->Struct,
                VersionValue,
                TEXT("CalculateBoundsMode"),
                Emitter);

            bool bDeterminismFound = false;
            bool bLocalSpaceFound = false;
            const bool bDeterminism = GetBoolField(
                VersionStruct->Struct,
                VersionValue,
                TEXT("bDeterminism"),
                bDeterminismFound);
            const bool bLocalSpace = GetBoolField(
                VersionStruct->Struct,
                VersionValue,
                TEXT("bLocalSpace"),
                bLocalSpaceFound);

            const int32 RendererCount = CountArray(
                VersionStruct->Struct,
                VersionValue,
                TEXT("RendererProperties"));
            const int32 SimulationStageCount = CountArray(
                VersionStruct->Struct,
                VersionValue,
                TEXT("SimulationStages"));
            const int32 EventHandlerCount = CountArray(
                VersionStruct->Struct,
                VersionValue,
                TEXT("EventHandlerScriptProps"));

            bool bVersionTruncated = false;
            TSharedRef<FJsonObject> VersionRow = MakeShared<FJsonObject>();
            VersionRow->SetStringField(TEXT("asset_path"), AssetPath);
            VersionRow->SetStringField(TEXT("emitter_path"), EmitterPath);
            VersionRow->SetNumberField(TEXT("version_index"), VersionIndex);
            VersionRow->SetStringField(TEXT("version"), VersionRaw);
            VersionRow->SetStringField(TEXT("sim_target"), SimTarget);
            VersionRow->SetStringField(TEXT("calculate_bounds_mode"), CalculateBoundsMode);
            if (bDeterminismFound)
            {
                VersionRow->SetBoolField(TEXT("determinism"), bDeterminism);
            }
            else
            {
                VersionRow->SetField(TEXT("determinism"), MakeShared<FJsonValueNull>());
            }
            if (bLocalSpaceFound)
            {
                VersionRow->SetBoolField(TEXT("local_space"), bLocalSpace);
            }
            else
            {
                VersionRow->SetField(TEXT("local_space"), MakeShared<FJsonValueNull>());
            }
            VersionRow->SetNumberField(TEXT("renderer_count"), RendererCount);
            VersionRow->SetNumberField(TEXT("simulation_stage_count"), SimulationStageCount);
            VersionRow->SetNumberField(TEXT("event_handler_count"), EventHandlerCount);
            VersionRow->SetStringField(
                TEXT("raw_value"),
                ExportProperty(VersionData->Inner, VersionValue, Emitter, bVersionTruncated));
            VersionRow->SetBoolField(TEXT("truncated"), bVersionTruncated);
            if (!Writers.NiagaraEmitterVersions.Write(VersionRow))
            {
                return false;
            }
            ++Counts.NiagaraEmitterVersions;

            if (FArrayProperty* Renderers = CastField<FArrayProperty>(
                VersionStruct->Struct->FindPropertyByName(TEXT("RendererProperties"))))
            {
                const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Renderers->Inner);
                const void* ValuePtr = Renderers->ContainerPtrToValuePtr<void>(VersionValue);
                if (Inner && ValuePtr)
                {
                    FScriptArrayHelper Helper(Renderers, ValuePtr);
                    for (int32 RendererIndex = 0; RendererIndex < Helper.Num(); ++RendererIndex)
                    {
                        UObject* Renderer = Inner->GetObjectPropertyValue(Helper.GetRawPtr(RendererIndex));
                        if (!Renderer)
                        {
                            continue;
                        }

                        bool bEnabledFound = false;
                        const bool bEnabled = GetBoolField(
                            Renderer->GetClass(),
                            Renderer,
                            TEXT("bIsEnabled"),
                            bEnabledFound);

                        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                        Row->SetStringField(TEXT("asset_path"), AssetPath);
                        Row->SetStringField(TEXT("emitter_path"), EmitterPath);
                        Row->SetNumberField(TEXT("version_index"), VersionIndex);
                        Row->SetNumberField(TEXT("renderer_index"), RendererIndex);
                        Row->SetStringField(TEXT("renderer_path"), Renderer->GetPathName());
                        Row->SetStringField(TEXT("renderer_class"), Renderer->GetClass()->GetPathName());
                        if (bEnabledFound)
                        {
                            Row->SetBoolField(TEXT("enabled"), bEnabled);
                        }
                        else
                        {
                            Row->SetField(TEXT("enabled"), MakeShared<FJsonValueNull>());
                        }
                        Row->SetStringField(TEXT("sort_order_hint"), ExportField(Renderer, TEXT("SortOrderHint")));
                        if (!Writers.NiagaraRenderers.Write(Row))
                        {
                            return false;
                        }
                        ++Counts.NiagaraRenderers;

                        if (!WriteObjectState(
                            Renderer,
                            AssetPath,
                            TEXT("niagara_renderer"),
                            Writers,
                            Counts,
                            SeenStateOwners))
                        {
                            return false;
                        }
                    }
                }
            }

            if (FArrayProperty* Stages = CastField<FArrayProperty>(
                VersionStruct->Struct->FindPropertyByName(TEXT("SimulationStages"))))
            {
                const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Stages->Inner);
                const void* ValuePtr = Stages->ContainerPtrToValuePtr<void>(VersionValue);
                if (Inner && ValuePtr)
                {
                    FScriptArrayHelper Helper(Stages, ValuePtr);
                    for (int32 StageIndex = 0; StageIndex < Helper.Num(); ++StageIndex)
                    {
                        UObject* Stage = Inner->GetObjectPropertyValue(Helper.GetRawPtr(StageIndex));
                        if (!Stage)
                        {
                            continue;
                        }

                        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                        Row->SetStringField(TEXT("asset_path"), AssetPath);
                        Row->SetStringField(TEXT("emitter_path"), EmitterPath);
                        Row->SetNumberField(TEXT("version_index"), VersionIndex);
                        Row->SetNumberField(TEXT("stage_index"), StageIndex);
                        Row->SetStringField(TEXT("stage_path"), Stage->GetPathName());
                        Row->SetStringField(TEXT("stage_class"), Stage->GetClass()->GetPathName());
                        Row->SetStringField(TEXT("script_usage_id"), ExportField(Stage, TEXT("ScriptUsageId")));
                        Row->SetStringField(TEXT("iteration_source"), ExportField(Stage, TEXT("IterationSource")));
                        if (!Writers.NiagaraSimulationStages.Write(Row))
                        {
                            return false;
                        }
                        ++Counts.NiagaraSimulationStages;

                        if (!WriteObjectState(
                            Stage,
                            AssetPath,
                            TEXT("niagara_simulation_stage"),
                            Writers,
                            Counts,
                            SeenStateOwners))
                        {
                            return false;
                        }
                    }
                }
            }
        }
    }

    bool bVersioningFound = false;
    const bool bVersioning = GetBoolField(
        Emitter->GetClass(),
        Emitter,
        TEXT("bVersioningEnabled"),
        bVersioningFound);

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("asset_path"), AssetPath);
    Summary->SetStringField(TEXT("emitter_path"), EmitterPath);
    Summary->SetStringField(TEXT("class_path"), Emitter->GetClass()->GetPathName());
    Summary->SetNumberField(TEXT("version_count"), VersionCount);
    Summary->SetStringField(TEXT("exposed_version"), ExportField(Emitter, TEXT("ExposedVersion")));
    if (bVersioningFound)
    {
        Summary->SetBoolField(TEXT("versioning_enabled"), bVersioning);
    }
    else
    {
        Summary->SetField(TEXT("versioning_enabled"), MakeShared<FJsonValueNull>());
    }
    if (!Writers.NiagaraEmitters.Write(Summary))
    {
        return false;
    }
    ++Counts.NiagaraEmitters;

    return WriteObjectState(
        Emitter,
        AssetPath,
        TEXT("niagara_emitter"),
        Writers,
        Counts,
        SeenStateOwners);
}
