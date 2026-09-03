#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolNavigationCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolNavigationCommandlet : public UCommandlet
{
    GENERATED_BODY()

public:
    UUnrealAssetToolNavigationCommandlet();
    virtual int32 Main(const FString& Params) override;
};
