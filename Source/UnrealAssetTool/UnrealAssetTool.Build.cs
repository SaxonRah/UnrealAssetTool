using UnrealBuildTool;

public class UnrealAssetTool : ModuleRules
{
    public UnrealAssetTool(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        // UnrealAssetTool is temporarily staged into other projects for scans.
        // In that staged location every source file can appear to UBT as part of
        // the adaptive working set, defeating unity and making cold builds pay
        // for every reflection-heavy translation unit independently. Prefer
        // unity for this scanner module; the canonical module-only build also
        // disables adaptive-unity exclusion for the isolated scanner build.
        bUseUnity = true;
        MinSourceFilesForUnityBuildOverride = 2;

        PublicDependencyModuleNames.AddRange(new[]
        {
            "Core",
            "CoreUObject",
            "Engine"
        });

        PrivateDependencyModuleNames.AddRange(new[]
        {
            "AnimGraph",
            "AssetRegistry",
            "BlueprintGraph",
            "DataflowCore",
            "DataflowEngine",
            "GameplayTags",
            "Json",
            "Projects",
            "RigVM",
            "RigVMDeveloper",
            "UnrealEd"
        });
    }
}
