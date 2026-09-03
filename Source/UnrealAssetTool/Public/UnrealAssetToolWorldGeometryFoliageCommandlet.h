#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolWorldGeometryFoliageCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolWorldGeometryFoliageCommandlet : public UCommandlet
{
    GENERATED_BODY()

public:
    UUnrealAssetToolWorldGeometryFoliageCommandlet();
    virtual int32 Main(const FString& Params) override;
};
