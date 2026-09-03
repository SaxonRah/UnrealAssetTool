#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolSkeletalMeshPhysicsAssetCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolSkeletalMeshPhysicsAssetCommandlet : public UCommandlet
{
    GENERATED_BODY()

public:
    UUnrealAssetToolSkeletalMeshPhysicsAssetCommandlet();
    virtual int32 Main(const FString& Params) override;
};
