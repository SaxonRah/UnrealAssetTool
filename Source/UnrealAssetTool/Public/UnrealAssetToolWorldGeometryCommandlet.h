#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolWorldGeometryCommandlet.generated.h"

UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolWorldGeometryCommandlet : public UCommandlet
{
    GENERATED_BODY()

public:
    UUnrealAssetToolWorldGeometryCommandlet();
    virtual int32 Main(const FString& Params) override;
};
