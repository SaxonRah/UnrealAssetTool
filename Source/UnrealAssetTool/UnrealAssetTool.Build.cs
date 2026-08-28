using UnrealBuildTool;

public class UnrealAssetTool : ModuleRules
{
    public UnrealAssetTool(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

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
            "Json",
            "Projects",
            "UnrealEd"
        });
    }
}
