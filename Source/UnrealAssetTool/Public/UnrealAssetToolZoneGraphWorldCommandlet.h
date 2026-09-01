#pragma once

#include "Commandlets/Commandlet.h"
#include "UnrealAssetToolZoneGraphWorldCommandlet.generated.h"

/**
 * Focused authored ZoneGraph world pass.
 *
 * The launcher supplies an exact list of already-indexed project worlds that
 * contain placed ZoneShape actors/components. This commandlet loads only those
 * worlds and normalizes authored ZoneShapeComponent/FZoneShapePoint state.
 * It deliberately does not claim generated FZoneGraphStorage lane topology.
 */
UCLASS()
class UNREALASSETTOOL_API UUnrealAssetToolZoneGraphWorldCommandlet : public UCommandlet
{
    GENERATED_BODY()

public:
    UUnrealAssetToolZoneGraphWorldCommandlet();

    virtual int32 Main(const FString& Params) override;
};
