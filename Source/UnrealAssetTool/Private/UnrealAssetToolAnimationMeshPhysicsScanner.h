#pragma once

#include "CoreMinimal.h"

namespace UnrealAssetToolAnimationMeshPhysics
{
/** Run the compact authored SkeletalMesh / PhysicsAsset pass into the canonical scan directory. */
bool RunScan(const FString& OutputDir, FString& OutError);
}
