// Real-corpus policy layer for systems schema 6 GAS extraction.
//
// The initial schema-6 implementation used AssetRegistry parent-name strings as
// a cheap Blueprint prefilter and enumerated every loaded AttributeSet class.
// Lyra proved both boundaries too weak: valid GA_* / GE_* Blueprints can derive
// through Blueprint parents whose names do not contain the semantic type, while
// the loaded class inventory also contains engine/test AttributeSets. Keep the
// reflection-first specialist writers, but make project scope + actual loaded
// inheritance authoritative here.

static bool GASClassInSystemsScope(
    const UClass* Class,
    const FString& ProjectDir,
    bool bIncludeEngine,
    bool bIncludeSelf,
    const FString& ToolPluginDir)
{
    if (!Class || !Class->GetOutermost())
    {
        return false;
    }

    const FString ClassName = Class->GetName();
    if (ClassName.StartsWith(TEXT("SKEL_")) ||
        ClassName.StartsWith(TEXT("REINST_")) ||
        ClassName.StartsWith(TEXT("TRASHCLASS_")))
    {
        return false;
    }

    const FString PackageName = Class->GetOutermost()->GetName();
    FString OwnerFilename;
    static const FString ScriptPrefix = TEXT("/Script/");
    if (PackageName.StartsWith(ScriptPrefix, ESearchCase::CaseSensitive))
    {
        const FString ModuleName = PackageName.Mid(ScriptPrefix.Len());
        if (ModuleName.IsEmpty())
        {
            return false;
        }
        OwnerFilename = FModuleManager::Get().GetModuleFilename(FName(*ModuleName));
    }
    else
    {
        FPackageName::DoesPackageExist(PackageName, &OwnerFilename, false);
    }

    if (OwnerFilename.IsEmpty())
    {
        // Unknown ownership must not silently become project truth. Include it
        // only when the caller explicitly requested engine-wide coverage.
        return bIncludeEngine;
    }

    OwnerFilename = NormalizeAbsolutePath(OwnerFilename);
    if (!bIncludeSelf && !ToolPluginDir.IsEmpty() &&
        IsInsideDirectory(OwnerFilename, ToolPluginDir))
    {
        return false;
    }
    return bIncludeEngine || IsInsideDirectory(OwnerFilename, ProjectDir);
}

static bool GASIsBlueprintAsset(const FAssetData& Asset)
{
    if (Asset.AssetClassPath == UBlueprint::StaticClass()->GetClassPathName())
    {
        return true;
    }

    // Gameplay Ability blueprints are registered by GameplayAbilities as the
    // specialized GameplayAbilityBlueprint asset class, not Engine.Blueprint.
    // Keep this as an exact reflected asset-class identity check: no asset name,
    // package name, or parent-name substring participates in semantic selection.
    return Asset.AssetClassPath.ToString().Equals(
        TEXT("/Script/GameplayAbilities.GameplayAbilityBlueprint"),
        ESearchCase::CaseSensitive);
}

static bool ScanGASProjectModelPolicy(
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
    for (const FAssetData& Asset : Assets)
    {
        if (!AssetInSystemsScope(
                Asset,
                ProjectDir,
                bIncludeEngine,
                bIncludeSelf,
                ToolPluginDir))
        {
            continue;
        }

        if (GASIsBlueprintAsset(Asset))
        {
            // Do not infer GAS membership from Blueprint/asset naming. Loading
            // project-scoped Blueprints and checking GeneratedClass inheritance
            // is authoritative and also handles chains through Blueprint parents.
            UBlueprint* Blueprint = Cast<UBlueprint>(Asset.GetAsset());
            if (!Blueprint || !Blueprint->GeneratedClass)
            {
                continue;
            }
            if (!GASWriteAbility(Blueprint, Asset, Writers, Counts, SeenStateOwners) ||
                !GASWriteGameplayEffect(Blueprint, Asset, Writers, Counts, SeenStateOwners) ||
                !GASWriteGameplayCue(Blueprint, Asset, Writers, Counts, SeenStateOwners))
            {
                OutError = TEXT("failed while scanning GAS Blueprint ") +
                    Asset.GetSoftObjectPath().ToString();
                return false;
            }
            continue;
        }

        const FString AssetClassPath = Asset.AssetClassPath.ToString();
        if (!AssetClassPath.Contains(TEXT("LyraAbilitySet")))
        {
            continue;
        }
        UObject* Object = Asset.GetAsset();
        if (Object && !GASWriteAbilitySet(
                Object,
                Asset,
                Writers,
                Counts,
                SeenStateOwners))
        {
            OutError = TEXT("failed while scanning GAS ability set ") +
                Asset.GetSoftObjectPath().ToString();
            return false;
        }
    }

    for (TObjectIterator<UClass> It; It; ++It)
    {
        UClass* Class = *It;
        if (!Class || !IsAttributeSetClass(Class) ||
            !GASClassInSystemsScope(
                Class,
                ProjectDir,
                bIncludeEngine,
                bIncludeSelf,
                ToolPluginDir))
        {
            continue;
        }
        if (!GASWriteAttributeSetClass(Class, Writers, Counts, SeenStateOwners))
        {
            OutError = TEXT("failed while scanning GAS AttributeSet class ") + Class->GetPathName();
            return false;
        }
    }
    return true;
}
