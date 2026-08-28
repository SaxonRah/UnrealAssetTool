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
            "AssetRegistry",
            "BlueprintGraph",
            "Json",
            "Projects",
            "UnrealEd"
        });
    }
}
