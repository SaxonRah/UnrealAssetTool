static bool ScanCascadeSystem(
    UObject* Object,
    const FAssetData& Asset,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    FArrayProperty* Emitters = CastField<FArrayProperty>(
        Object->GetClass()->FindPropertyByName(TEXT("Emitters")));
    const FObjectPropertyBase* EmitterInner = Emitters
        ? CastField<FObjectPropertyBase>(Emitters->Inner)
        : nullptr;
    const void* EmittersValue = Emitters
        ? Emitters->ContainerPtrToValuePtr<void>(Object)
        : nullptr;

    int32 EmitterCount = 0;
    if (Emitters && EmitterInner && EmittersValue)
    {
        FScriptArrayHelper EmitterHelper(Emitters, EmittersValue);
        EmitterCount = EmitterHelper.Num();

        for (int32 EmitterIndex = 0; EmitterIndex < EmitterHelper.Num(); ++EmitterIndex)
        {
            UObject* Emitter = EmitterInner->GetObjectPropertyValue(
                EmitterHelper.GetRawPtr(EmitterIndex));
            if (!Emitter)
            {
                continue;
            }

            FArrayProperty* LODLevels = CastField<FArrayProperty>(
                Emitter->GetClass()->FindPropertyByName(TEXT("LODLevels")));
            const FObjectPropertyBase* LODInner = LODLevels
                ? CastField<FObjectPropertyBase>(LODLevels->Inner)
                : nullptr;
            const void* LODValue = LODLevels
                ? LODLevels->ContainerPtrToValuePtr<void>(Emitter)
                : nullptr;
            const int32 LODCount = LODLevels && LODValue
                ? FScriptArrayHelper(LODLevels, LODValue).Num()
                : 0;

            TSharedRef<FJsonObject> EmitterRow = MakeShared<FJsonObject>();
            EmitterRow->SetStringField(TEXT("system_path"), AssetPath);
            EmitterRow->SetNumberField(TEXT("emitter_index"), EmitterIndex);
            EmitterRow->SetStringField(TEXT("emitter_path"), Emitter->GetPathName());
            EmitterRow->SetStringField(TEXT("emitter_class"), Emitter->GetClass()->GetPathName());
            EmitterRow->SetStringField(TEXT("emitter_name"), GetNameField(
                Emitter->GetClass(),
                Emitter,
                TEXT("EmitterName"),
                Emitter));
            EmitterRow->SetNumberField(TEXT("lod_count"), LODCount);
            EmitterRow->SetStringField(TEXT("significance_level"), ExportField(
                Emitter,
                TEXT("SignificanceLevel")));
            if (!Writers.CascadeEmitters.Write(EmitterRow))
            {
                return false;
            }
            ++Counts.CascadeEmitters;

            if (!WriteObjectState(
                Emitter,
                AssetPath,
                TEXT("cascade_emitter"),
                Writers,
                Counts,
                SeenStateOwners))
            {
                return false;
            }

            if (LODLevels && LODInner && LODValue)
            {
                FScriptArrayHelper LODHelper(LODLevels, LODValue);
                for (int32 LODIndex = 0; LODIndex < LODHelper.Num(); ++LODIndex)
                {
                    UObject* LOD = LODInner->GetObjectPropertyValue(LODHelper.GetRawPtr(LODIndex));
                    if (!LOD)
                    {
                        continue;
                    }

                    bool bEnabledFound = false;
                    const bool bEnabled = GetBoolField(
                        LOD->GetClass(),
                        LOD,
                        TEXT("bEnabled"),
                        bEnabledFound);
                    const int32 ModuleArrayCount = CountArray(
                        LOD->GetClass(),
                        LOD,
                        TEXT("Modules"));

                    TSharedRef<FJsonObject> LODRow = MakeShared<FJsonObject>();
                    LODRow->SetStringField(TEXT("system_path"), AssetPath);
                    LODRow->SetNumberField(TEXT("emitter_index"), EmitterIndex);
                    LODRow->SetNumberField(TEXT("lod_index"), LODIndex);
                    LODRow->SetStringField(TEXT("lod_path"), LOD->GetPathName());
                    LODRow->SetStringField(TEXT("level"), ExportField(LOD, TEXT("Level")));
                    if (bEnabledFound)
                    {
                        LODRow->SetBoolField(TEXT("enabled"), bEnabled);
                    }
                    else
                    {
                        LODRow->SetField(TEXT("enabled"), MakeShared<FJsonValueNull>());
                    }
                    LODRow->SetNumberField(TEXT("module_array_count"), ModuleArrayCount);
                    if (!Writers.CascadeLODs.Write(LODRow))
                    {
                        return false;
                    }
                    ++Counts.CascadeLODs;

                    if (!WriteObjectState(
                        LOD,
                        AssetPath,
                        TEXT("cascade_lod"),
                        Writers,
                        Counts,
                        SeenStateOwners))
                    {
                        return false;
                    }

                    TSet<FString> SeenModules;
                    int32 ModuleIndex = 0;
                    const auto EmitModule = [&](UObject* Module, const FString& Role) -> bool
                    {
                        if (!Module)
                        {
                            return true;
                        }

                        const FString ModulePath = Module->GetPathName();
                        const FString DedupKey = Role + TEXT("|") + ModulePath;
                        if (SeenModules.Contains(DedupKey))
                        {
                            return true;
                        }
                        SeenModules.Add(DedupKey);

                        TSharedRef<FJsonObject> ModuleRow = MakeShared<FJsonObject>();
                        ModuleRow->SetStringField(TEXT("system_path"), AssetPath);
                        ModuleRow->SetNumberField(TEXT("emitter_index"), EmitterIndex);
                        ModuleRow->SetNumberField(TEXT("lod_index"), LODIndex);
                        ModuleRow->SetNumberField(TEXT("module_index"), ModuleIndex++);
                        ModuleRow->SetStringField(TEXT("role"), Role);
                        ModuleRow->SetStringField(TEXT("module_path"), ModulePath);
                        ModuleRow->SetStringField(TEXT("module_class"), Module->GetClass()->GetPathName());
                        if (!Writers.CascadeModules.Write(ModuleRow))
                        {
                            return false;
                        }
                        ++Counts.CascadeModules;

                        return WriteObjectState(
                            Module,
                            AssetPath,
                            TEXT("cascade_module"),
                            Writers,
                            Counts,
                            SeenStateOwners);
                    };

                    if (!EmitModule(GetObjectField(LOD, TEXT("RequiredModule")), TEXT("required")))
                    {
                        return false;
                    }
                    if (!EmitModule(GetObjectField(LOD, TEXT("SpawnModule")), TEXT("spawn")))
                    {
                        return false;
                    }
                    if (!EmitModule(GetObjectField(LOD, TEXT("TypeDataModule")), TEXT("type_data")))
                    {
                        return false;
                    }

                    if (FArrayProperty* Modules = CastField<FArrayProperty>(
                        LOD->GetClass()->FindPropertyByName(TEXT("Modules"))))
                    {
                        const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Modules->Inner);
                        const void* ValuePtr = Modules->ContainerPtrToValuePtr<void>(LOD);
                        if (Inner && ValuePtr)
                        {
                            FScriptArrayHelper Helper(Modules, ValuePtr);
                            for (int32 Index = 0; Index < Helper.Num(); ++Index)
                            {
                                if (!EmitModule(
                                    Inner->GetObjectPropertyValue(Helper.GetRawPtr(Index)),
                                    TEXT("module")))
                                {
                                    return false;
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    TSharedRef<FJsonObject> Summary = MakeShared<FJsonObject>();
    Summary->SetStringField(TEXT("system_path"), AssetPath);
    Summary->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Summary->SetNumberField(TEXT("emitter_count"), EmitterCount);
    Summary->SetStringField(TEXT("warmup_time"), ExportField(Object, TEXT("WarmupTime")));
    Summary->SetStringField(TEXT("delay"), ExportField(Object, TEXT("Delay")));
    Summary->SetStringField(TEXT("lod_method"), ExportField(Object, TEXT("LODMethod")));
    if (!Writers.CascadeSystems.Write(Summary))
    {
        return false;
    }
    ++Counts.CascadeSystems;
    return true;
}
