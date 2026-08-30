static bool WriteProperties(
    UObject* Object,
    const FString& AssetPath,
    const FString& OwnerKind,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Object)
    {
        return true;
    }

    TSet<FString> Seen;
    for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property))
            {
                continue;
            }

            const FString Key = Class->GetPathName() + TEXT("::") + Property->GetName();
            if (Seen.Contains(Key))
            {
                continue;
            }
            Seen.Add(Key);

            bool bTruncated = false;
            const FString Value = ExportProperty(
                Property,
                Property->ContainerPtrToValuePtr<void>(Object),
                Object,
                bTruncated);

            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("asset_path"), AssetPath);
            Row->SetStringField(TEXT("owner_path"), Object->GetPathName());
            Row->SetStringField(TEXT("owner_kind"), OwnerKind);
            Row->SetStringField(TEXT("owner_class"), Object->GetClass()->GetPathName());
            Row->SetStringField(TEXT("declaring_type"), Class->GetPathName());
            Row->SetStringField(TEXT("property_name"), Property->GetName());
            Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
            Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
            Row->SetStringField(TEXT("value"), Value);
            Row->SetBoolField(TEXT("truncated"), bTruncated);
            if (!Writers.Properties.Write(Row))
            {
                return false;
            }
            ++Counts.Properties;
        }
    }
    return true;
}

struct FReferenceContext
{
    FString AssetPath;
    FString OwnerPath;
    FString OwnerKind;
    FString RootProperty;
    int32 Rows = 0;
    FWriters* Writers = nullptr;
    FCounts* Counts = nullptr;
};

static void EmitReference(
    FReferenceContext& Context,
    const FString& PropertyPath,
    const FString& ReferenceKind,
    const FString& TargetPath,
    const FString& TargetClass)
{
    if (!Context.Writers || !Context.Counts || TargetPath.IsEmpty() || Context.Rows >= MaxReferencesPerRoot)
    {
        return;
    }

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("asset_path"), Context.AssetPath);
    Row->SetStringField(TEXT("owner_path"), Context.OwnerPath);
    Row->SetStringField(TEXT("owner_kind"), Context.OwnerKind);
    Row->SetStringField(TEXT("root_property"), Context.RootProperty);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), ReferenceKind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (Context.Writers->References.Write(Row))
    {
        ++Context.Rows;
        ++Context.Counts->References;
    }
}

static void CollectReferences(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& PropertyPath,
    int32 Depth,
    FReferenceContext& Context)
{
    if (!Property || !ValuePtr || Depth > MaxReferenceDepth || Context.Rows >= MaxReferencesPerRoot)
    {
        return;
    }

    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* SoftPtr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (SoftPtr && !SoftPtr->IsNull())
        {
            EmitReference(
                Context,
                PropertyPath,
                TEXT("soft_object"),
                SoftPtr->ToSoftObjectPath().ToString(),
                FString());
        }
        return;
    }

    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr);
        if (Target)
        {
            EmitReference(
                Context,
                PropertyPath,
                TEXT("hard_object"),
                Target->GetPathName(),
                Target->GetClass()->GetPathName());
        }
        return;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        if (!StructProperty->Struct)
        {
            return;
        }

        for (TFieldIterator<FProperty> It(StructProperty->Struct); It; ++It)
        {
            const FProperty* Inner = *It;
            if (!ShouldInspectProperty(Inner))
            {
                continue;
            }

            for (int32 StaticIndex = 0; StaticIndex < Inner->ArrayDim; ++StaticIndex)
            {
                const void* InnerValue = Inner->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                const FString Child = PropertyPath + TEXT(".") + Inner->GetName() +
                    (Inner->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                CollectReferences(Inner, InnerValue, Child, Depth + 1, Context);
            }
        }
        return;
    }

    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, ValuePtr);
        const int32 Limit = FMath::Min(Helper.Num(), 4096);
        for (int32 Index = 0; Index < Limit; ++Index)
        {
            CollectReferences(
                ArrayProperty->Inner,
                Helper.GetRawPtr(Index),
                FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                Depth + 1,
                Context);
        }
        return;
    }

    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        FScriptSetHelper Helper(SetProperty, ValuePtr);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < 4096; ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }
            CollectReferences(
                SetProperty->ElementProp,
                Helper.GetElementPtr(Index),
                FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++),
                Depth + 1,
                Context);
        }
        return;
    }

    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        FScriptMapHelper Helper(MapProperty, ValuePtr);
        int32 Emitted = 0;
        for (int32 Index = 0; Index < Helper.GetMaxIndex() && Emitted < 4096; ++Index)
        {
            if (!Helper.IsValidIndex(Index))
            {
                continue;
            }

            const FString Base = FString::Printf(TEXT("%s{%d}"), *PropertyPath, Emitted++);
            CollectReferences(MapProperty->KeyProp, Helper.GetKeyPtr(Index), Base + TEXT(".key"), Depth + 1, Context);
            CollectReferences(MapProperty->ValueProp, Helper.GetValuePtr(Index), Base + TEXT(".value"), Depth + 1, Context);
        }
    }
}

static void WriteReferences(
    UObject* Object,
    const FString& AssetPath,
    const FString& OwnerKind,
    FWriters& Writers,
    FCounts& Counts)
{
    if (!Object)
    {
        return;
    }

    for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            FProperty* Property = *It;
            if (!ShouldInspectProperty(Property))
            {
                continue;
            }

            FReferenceContext Context;
            Context.AssetPath = AssetPath;
            Context.OwnerPath = Object->GetPathName();
            Context.OwnerKind = OwnerKind;
            Context.RootProperty = Property->GetName();
            Context.Writers = &Writers;
            Context.Counts = &Counts;

            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
            {
                const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object, StaticIndex);
                const FString Path = Property->GetName() +
                    (Property->ArrayDim > 1 ? FString::Printf(TEXT("[%d]"), StaticIndex) : FString());
                CollectReferences(Property, ValuePtr, Path, 0, Context);
            }
        }
    }
}

static FString KindForClass(const FString& ClassPath)
{
    if (ClassPath == TEXT("/Script/Niagara.NiagaraSystem")) return TEXT("niagara_system");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraEmitter")) return TEXT("niagara_emitter");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraStatelessEmitter")) return TEXT("niagara_stateless_emitter");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraScript")) return TEXT("niagara_script");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraDataChannelAsset")) return TEXT("niagara_data_channel");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraParameterCollection")) return TEXT("niagara_parameter_collection");
    if (ClassPath == TEXT("/Script/Niagara.NiagaraEffectType")) return TEXT("niagara_effect_type");
    if (ClassPath == TEXT("/Script/Engine.ParticleSystem")) return TEXT("cascade_particle_system");
    return FString();
}

static bool WriteObjectState(
    UObject* Object,
    const FString& AssetPath,
    const FString& OwnerKind,
    FWriters& Writers,
    FCounts& Counts,
    TSet<FString>& SeenStateOwners)
{
    if (!Object)
    {
        return true;
    }

    const FString Path = Object->GetPathName();
    if (SeenStateOwners.Contains(Path))
    {
        return true;
    }
    SeenStateOwners.Add(Path);

    if (!WriteProperties(Object, AssetPath, OwnerKind, Writers, Counts))
    {
        return false;
    }
    WriteReferences(Object, AssetPath, OwnerKind, Writers, Counts);
    return true;
}
