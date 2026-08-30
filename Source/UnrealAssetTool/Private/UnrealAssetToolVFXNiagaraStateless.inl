static bool WriteNiagaraStatelessEmitterObject(
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

    FArrayProperty* Modules = FindArrayField(Emitter->GetClass(), TEXT("Modules"));
    FArrayProperty* Renderers = FindArrayField(Emitter->GetClass(), TEXT("RendererProperties"));
    const int32 ModuleCount = CountArray(Emitter->GetClass(), Emitter, TEXT("Modules"));
    const int32 RendererCount = CountArray(Emitter->GetClass(), Emitter, TEXT("RendererProperties"));

    bool bDeterministicFound = false;
    const bool bDeterministic = GetBoolField(
        Emitter->GetClass(),
        Emitter,
        TEXT("bDeterministic"),
        bDeterministicFound);

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("asset_path"), AssetPath);
    Summary->SetStringField(TEXT("emitter_path"), EmitterPath);
    Summary->SetStringField(TEXT("class_path"), Emitter->GetClass()->GetPathName());
    Summary->SetNumberField(TEXT("module_count"), ModuleCount);
    Summary->SetNumberField(TEXT("renderer_count"), RendererCount);
    if (bDeterministicFound)
    {
        Summary->SetBoolField(TEXT("deterministic"), bDeterministic);
    }
    else
    {
        Summary->SetField(TEXT("deterministic"), MakeShared<FJsonValueNull>());
    }
    Summary->SetStringField(TEXT("random_seed"), ExportField(Emitter, TEXT("RandomSeed")));
    Summary->SetStringField(TEXT("fixed_bounds"), ExportField(Emitter, TEXT("FixedBounds")));
    if (!Writers.NiagaraStatelessEmitters.Write(Summary))
    {
        return false;
    }
    ++Counts.NiagaraStatelessEmitters;

    if (!WriteObjectState(
        Emitter,
        AssetPath,
        TEXT("niagara_stateless_emitter"),
        Writers,
        Counts,
        SeenStateOwners))
    {
        return false;
    }

    if (Modules)
    {
        const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Modules->Inner);
        const void* ValuePtr = Modules->ContainerPtrToValuePtr<void>(Emitter);
        if (Inner && ValuePtr)
        {
            FScriptArrayHelper Helper(Modules, ValuePtr);
            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                UObject* Module = Inner->GetObjectPropertyValue(Helper.GetRawPtr(Index));
                if (!Module)
                {
                    continue;
                }

                bool bEnabledFound = false;
                bool bEnabled = GetBoolField(
                    Module->GetClass(),
                    Module,
                    TEXT("bModuleEnabled"),
                    bEnabledFound);
                if (!bEnabledFound)
                {
                    bEnabled = GetBoolField(
                        Module->GetClass(),
                        Module,
                        TEXT("bEnabled"),
                        bEnabledFound);
                }

                TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
                Row->SetStringField(TEXT("asset_path"), AssetPath);
                Row->SetStringField(TEXT("emitter_path"), EmitterPath);
                Row->SetNumberField(TEXT("module_index"), Index);
                Row->SetStringField(TEXT("module_path"), Module->GetPathName());
                Row->SetStringField(TEXT("module_class"), Module->GetClass()->GetPathName());
                if (bEnabledFound)
                {
                    Row->SetBoolField(TEXT("enabled"), bEnabled);
                }
                else
                {
                    Row->SetField(TEXT("enabled"), MakeShared<FJsonValueNull>());
                }
                if (!Writers.NiagaraStatelessModules.Write(Row))
                {
                    return false;
                }
                ++Counts.NiagaraStatelessModules;

                if (!WriteObjectState(
                    Module,
                    AssetPath,
                    TEXT("niagara_stateless_module"),
                    Writers,
                    Counts,
                    SeenStateOwners))
                {
                    return false;
                }
            }
        }
    }

    if (Renderers)
    {
        const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Renderers->Inner);
        const void* ValuePtr = Renderers->ContainerPtrToValuePtr<void>(Emitter);
        if (Inner && ValuePtr)
        {
            FScriptArrayHelper Helper(Renderers, ValuePtr);
            for (int32 Index = 0; Index < Helper.Num(); ++Index)
            {
                UObject* Renderer = Inner->GetObjectPropertyValue(Helper.GetRawPtr(Index));
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
                Row->SetNumberField(TEXT("renderer_index"), Index);
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
                if (!Writers.NiagaraStatelessRenderers.Write(Row))
                {
                    return false;
                }
                ++Counts.NiagaraStatelessRenderers;

                if (!WriteObjectState(
                    Renderer,
                    AssetPath,
                    TEXT("niagara_stateless_renderer"),
                    Writers,
                    Counts,
                    SeenStateOwners))
                {
                    return false;
                }
            }
        }
    }

    return true;
}

static bool ScanNiagaraSystem(
    UObject* Object,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenEmitters,
    TSet<FString>& SeenStatelessEmitters,
    TSet<FString>& SeenStateOwners)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    FArrayProperty* Handles = CastField<FArrayProperty>(
        Object->GetClass()->FindPropertyByName(TEXT("EmitterHandles")));
    const FStructProperty* HandleStruct = Handles
        ? CastField<FStructProperty>(Handles->Inner)
        : nullptr;
    const void* ArrayValue = Handles
        ? Handles->ContainerPtrToValuePtr<void>(Object)
        : nullptr;

    int32 HandleCount = 0;
    if (Handles && HandleStruct && ArrayValue)
    {
        FScriptArrayHelper Helper(Handles, ArrayValue);
        HandleCount = Helper.Num();

        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Handle = Helper.GetRawPtr(Index);
            UObject* StatelessEmitter = GetObjectField(
                HandleStruct->Struct,
                Handle,
                TEXT("StatelessEmitter"));

            UObject* Emitter = nullptr;
            FString Version;
            if (const FStructProperty* Versioned = CastField<FStructProperty>(
                HandleStruct->Struct->FindPropertyByName(TEXT("VersionedInstance"))))
            {
                const void* VersionedValue = Versioned->ContainerPtrToValuePtr<void>(Handle);
                Emitter = GetObjectField(
                    Versioned->Struct,
                    VersionedValue,
                    TEXT("Emitter"));
                Version = ExportField(
                    Versioned->Struct,
                    VersionedValue,
                    TEXT("Version"),
                    Object);
            }

            bool bEnabledFound = false;
            const bool bEnabled = GetBoolField(
                HandleStruct->Struct,
                Handle,
                TEXT("bIsEnabled"),
                bEnabledFound);
            bool bTruncated = false;

            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("system_path"), AssetPath);
            Row->SetNumberField(TEXT("emitter_index"), Index);
            Row->SetStringField(TEXT("name"), GetNameField(HandleStruct->Struct, Handle, TEXT("Name"), Object));
            Row->SetStringField(TEXT("id"), ExportField(HandleStruct->Struct, Handle, TEXT("Id"), Object));
            Row->SetStringField(TEXT("id_name"), GetNameField(HandleStruct->Struct, Handle, TEXT("IdName"), Object));
            if (bEnabledFound)
            {
                Row->SetBoolField(TEXT("enabled"), bEnabled);
            }
            else
            {
                Row->SetField(TEXT("enabled"), MakeShared<FJsonValueNull>());
            }
            Row->SetStringField(TEXT("emitter_mode"), ExportField(HandleStruct->Struct, Handle, TEXT("EmitterMode"), Object));
            Row->SetStringField(TEXT("emitter_path"), Emitter ? Emitter->GetPathName() : FString());
            Row->SetStringField(TEXT("emitter_class"), Emitter ? Emitter->GetClass()->GetPathName() : FString());
            Row->SetStringField(TEXT("emitter_version"), Version);
            Row->SetStringField(TEXT("stateless_emitter_path"), StatelessEmitter ? StatelessEmitter->GetPathName() : FString());
            Row->SetStringField(TEXT("stateless_emitter_class"), StatelessEmitter ? StatelessEmitter->GetClass()->GetPathName() : FString());
            Row->SetStringField(TEXT("raw_value"), ExportProperty(Handles->Inner, Handle, Object, bTruncated));
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.NiagaraSystemEmitters.Write(Row))
            {
                return false;
            }
            ++Counts.NiagaraSystemEmitters;

            if (Emitter && !WriteNiagaraEmitterObject(
                Emitter,
                AssetPath,
                Writers,
                Counts,
                SeenEmitters,
                SeenStateOwners))
            {
                return false;
            }

            if (StatelessEmitter && !WriteNiagaraStatelessEmitterObject(
                StatelessEmitter,
                AssetPath,
                Writers,
                Counts,
                SeenStatelessEmitters,
                SeenStateOwners))
            {
                return false;
            }
        }
    }

    UObject* EffectType = GetObjectField(Object, TEXT("EffectType"));
    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("system_path"), AssetPath);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetNumberField(TEXT("emitter_count"), HandleCount);
    Summary->SetStringField(TEXT("effect_type_path"), EffectType ? EffectType->GetPathName() : FString());
    Summary->SetStringField(TEXT("warmup_time"), ExportField(Object, TEXT("WarmupTime")));
    Summary->SetStringField(TEXT("warmup_tick_delta"), ExportField(Object, TEXT("WarmupTickDelta")));
    Summary->SetStringField(TEXT("fixed_bounds"), ExportField(Object, TEXT("FixedBounds")));
    if (!Writers.NiagaraSystems.Write(Summary))
    {
        return false;
    }
    ++Counts.NiagaraSystems;
    return true;
}
