#include "UnrealAssetToolWorldGeometryCommandlet.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolWorldGeometry
{
constexpr int32 SchemaVersion = 1;
constexpr int32 MaxExportChars = 32768;

static const TCHAR* LandscapeClass = TEXT("/Script/Landscape.Landscape");
static const TCHAR* LandscapeStreamingProxyClass = TEXT("/Script/Landscape.LandscapeStreamingProxy");
static const TCHAR* LandscapeLayerInfoClass = TEXT("/Script/Landscape.LandscapeLayerInfoObject");
static const TCHAR* LandscapeGrassTypeClass = TEXT("/Script/Landscape.LandscapeGrassType");
static const TCHAR* FoliageTypeClass = TEXT("/Script/Foliage.FoliageType_InstancedStaticMesh");
static const TCHAR* InstancedFoliageActorClass = TEXT("/Script/Foliage.InstancedFoliageActor");
static const TCHAR* HLODLayerClass = TEXT("/Script/Engine.HLODLayer");

static const TCHAR* LandscapeRootProperties[] = {
    TEXT("LandscapeMaterial"), TEXT("LandscapeHoleMaterial"), TEXT("DefaultPhysMaterial"),
    TEXT("ComponentSizeQuads"), TEXT("LandscapeSectionOffset"), TEXT("NumSubsections"),
    TEXT("SubsectionSizeQuads"), TEXT("MaxLODLevel"), TEXT("LODDistanceFactor"),
    TEXT("NegativeZBoundsExtension"), TEXT("PositiveZBoundsExtension"), TEXT("bUseDynamicMaterialInstance"),
    TEXT("bNaniteEnabled"), TEXT("NaniteLODIndex"), TEXT("NaniteSkirtDepth"),
    TEXT("bBakeMaterialPositionOffsetIntoCollision"), TEXT("bUseMaterialPositionOffsetInStaticLighting")
};

static const TCHAR* LandscapeComponentProperties[] = {
    TEXT("SectionBaseX"), TEXT("SectionBaseY"), TEXT("ComponentSizeQuads"),
    TEXT("NumSubsections"), TEXT("SubsectionSizeQuads"), TEXT("HeightmapScaleBias"),
    TEXT("WeightmapScaleBias"), TEXT("WeightmapSubsectionOffset"), TEXT("HeightmapTexture"),
    TEXT("XYOffsetmapTexture"), TEXT("OverrideMaterial"), TEXT("OverrideHoleMaterial"),
    TEXT("EditToolRenderData"), TEXT("LayersData")
};

struct FCounts
{
    int64 RegistryCandidates = 0;
    int64 LoadFailures = 0;
    int64 LandscapeRoots = 0;
    int64 LandscapeComponents = 0;
    int64 LandscapeWeightmapAllocations = 0;
    int64 LandscapeLayerInfos = 0;
    int64 LandscapeGrassTypes = 0;
    int64 LandscapeGrassVarieties = 0;
    int64 FoliageTypes = 0;
    int64 FoliageActors = 0;
    int64 FoliageActorTypeInfos = 0;
    int64 FoliageInstances = 0;
    int64 FoliageInfoMapsOpaque = 0;
    int64 HLODLayers = 0;
    int64 PropertyRows = 0;
};

class FJsonlWriter
{
public:
    bool Open(const FString& Filename)
    {
        IFileManager::Get().MakeDirectory(*FPaths::GetPath(Filename), true);
        Archive.Reset(IFileManager::Get().CreateFileWriter(*Filename));
        return Archive.IsValid();
    }

    bool Write(const TSharedRef<FJsonObject>& Object)
    {
        if (!Archive.IsValid()) return false;
        FString Line;
        const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
            TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);
        if (!FJsonSerializer::Serialize(Object, Writer)) return false;
        Line.AppendChar(TEXT('\n'));
        FTCHARToUTF8 Utf8(*Line);
        Archive->Serialize((void*)Utf8.Get(), Utf8.Length());
        return !Archive->IsError();
    }

    bool Close()
    {
        if (!Archive.IsValid()) return true;
        const bool bClosed = Archive->Close();
        const bool bOk = bClosed && !Archive->IsError();
        Archive.Reset();
        return bOk;
    }

    ~FJsonlWriter() { Close(); }

private:
    TUniquePtr<FArchive> Archive;
};

struct FWriters
{
    FJsonlWriter LandscapeRoots;
    FJsonlWriter LandscapeComponents;
    FJsonlWriter LandscapeAllocations;
    FJsonlWriter LandscapeLayerInfos;
    FJsonlWriter LandscapeGrassTypes;
    FJsonlWriter LandscapeGrassVarieties;
    FJsonlWriter FoliageTypes;
    FJsonlWriter FoliageActors;
    FJsonlWriter FoliageActorTypeInfos;
    FJsonlWriter FoliageInstances;
    FJsonlWriter HLODLayers;
    FJsonlWriter Properties;

    bool Open(const FString& OutputDir)
    {
        return LandscapeRoots.Open(FPaths::Combine(OutputDir, TEXT("landscape_roots.jsonl"))) &&
            LandscapeComponents.Open(FPaths::Combine(OutputDir, TEXT("landscape_components.jsonl"))) &&
            LandscapeAllocations.Open(FPaths::Combine(OutputDir, TEXT("landscape_weightmap_allocations.jsonl"))) &&
            LandscapeLayerInfos.Open(FPaths::Combine(OutputDir, TEXT("landscape_layer_infos.jsonl"))) &&
            LandscapeGrassTypes.Open(FPaths::Combine(OutputDir, TEXT("landscape_grass_types.jsonl"))) &&
            LandscapeGrassVarieties.Open(FPaths::Combine(OutputDir, TEXT("landscape_grass_varieties.jsonl"))) &&
            FoliageTypes.Open(FPaths::Combine(OutputDir, TEXT("foliage_types.jsonl"))) &&
            FoliageActors.Open(FPaths::Combine(OutputDir, TEXT("foliage_actors.jsonl"))) &&
            FoliageActorTypeInfos.Open(FPaths::Combine(OutputDir, TEXT("foliage_actor_type_infos.jsonl"))) &&
            FoliageInstances.Open(FPaths::Combine(OutputDir, TEXT("foliage_instances.jsonl"))) &&
            HLODLayers.Open(FPaths::Combine(OutputDir, TEXT("hlod_layers.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("world_geometry_properties.jsonl")));
    }

    bool Close()
    {
        bool bOk = true;
        bOk = LandscapeRoots.Close() && bOk;
        bOk = LandscapeComponents.Close() && bOk;
        bOk = LandscapeAllocations.Close() && bOk;
        bOk = LandscapeLayerInfos.Close() && bOk;
        bOk = LandscapeGrassTypes.Close() && bOk;
        bOk = LandscapeGrassVarieties.Close() && bOk;
        bOk = FoliageTypes.Close() && bOk;
        bOk = FoliageActors.Close() && bOk;
        bOk = FoliageActorTypeInfos.Close() && bOk;
        bOk = FoliageInstances.Close() && bOk;
        bOk = HLODLayers.Close() && bOk;
        bOk = Properties.Close() && bOk;
        return bOk;
    }
};

static FString NormalizeAbsolutePath(const FString& InPath)
{
    FString Path = FPaths::ConvertRelativePathToFull(InPath);
    FPaths::NormalizeFilename(Path);
    FPaths::CollapseRelativeDirectories(Path);
    return Path;
}

static bool IsInsideDirectory(const FString& File, const FString& Directory)
{
    FString NormalizedFile = NormalizeAbsolutePath(File);
    FString NormalizedDirectory = NormalizeAbsolutePath(Directory);
    if (!NormalizedDirectory.EndsWith(TEXT("/"))) NormalizedDirectory.AppendChar(TEXT('/'));
    return NormalizedFile.StartsWith(NormalizedDirectory, ESearchCase::IgnoreCase);
}

static bool AssetInScope(const FAssetData& Asset, const FString& ProjectDir, bool bIncludeEngine)
{
    if (bIncludeEngine) return true;
    FString Filename;
    FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &Filename, false);
    return !Filename.IsEmpty() && IsInsideDirectory(Filename, ProjectDir);
}

static bool IsCandidateClass(const FString& ClassPath)
{
    return ClassPath == LandscapeClass || ClassPath == LandscapeStreamingProxyClass ||
        ClassPath == LandscapeLayerInfoClass || ClassPath == LandscapeGrassTypeClass ||
        ClassPath == FoliageTypeClass || ClassPath == InstancedFoliageActorClass ||
        ClassPath == HLODLayerClass;
}

static bool ShouldInspectProperty(const FProperty* Property)
{
    if (!Property) return false;
    constexpr EPropertyFlags Rejected =
        CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient |
        CPF_Deprecated | CPF_SkipSerialization;
    return !Property->HasAnyPropertyFlags(Rejected);
}

static FString ExportProperty(const FProperty* Property, const void* ValuePtr, UObject* Owner)
{
    if (!Property || !ValuePtr) return FString();
    FString Text;
    Property->ExportTextItem_Direct(Text, ValuePtr, nullptr, Owner, PPF_None, nullptr);
    if (Text.Len() > MaxExportChars) Text.LeftInline(MaxExportChars, EAllowShrinking::No);
    return Text;
}

static FString ObjectPath(UObject* Object)
{
    return Object ? Object->GetPathName() : FString();
}

static FString ObjectClass(UObject* Object)
{
    return Object ? Object->GetClass()->GetPathName() : FString();
}

static UObject* ObjectField(UObject* Object, const TCHAR* Name)
{
    if (!Object) return nullptr;
    const FObjectPropertyBase* Field = CastField<FObjectPropertyBase>(Object->GetClass()->FindPropertyByName(FName(Name)));
    return Field ? Field->GetObjectPropertyValue(Field->ContainerPtrToValuePtr<void>(Object)) : nullptr;
}

static FString ObjectFieldText(UObject* Object, const TCHAR* Name)
{
    if (!Object) return FString();
    const FProperty* Field = Object->GetClass()->FindPropertyByName(FName(Name));
    if (!Field || !ShouldInspectProperty(Field)) return FString();
    return ExportProperty(Field, Field->ContainerPtrToValuePtr<void>(Object), Object);
}

static int32 ArrayCount(UObject* Object, const TCHAR* Name)
{
    if (!Object) return 0;
    const FArrayProperty* Array = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(FName(Name)));
    if (!Array) return 0;
    FScriptArrayHelper Helper(Array, Array->ContainerPtrToValuePtr<void>(Object));
    return Helper.Num();
}

static TSharedRef<FJsonObject> StructFields(const UStruct* Struct, const void* ValuePtr, UObject* Owner)
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    if (!Struct || !ValuePtr) return Result;
    for (TFieldIterator<FProperty> It(Struct); It; ++It)
    {
        const FProperty* Field = *It;
        if (!ShouldInspectProperty(Field)) continue;
        if (CastField<FArrayProperty>(Field) || CastField<FMapProperty>(Field) || CastField<FSetProperty>(Field)) continue;
        for (int32 StaticIndex = 0; StaticIndex < Field->ArrayDim; ++StaticIndex)
        {
            FString Key = Field->GetName();
            if (Field->ArrayDim > 1) Key += FString::Printf(TEXT("[%d]"), StaticIndex);
            Result->SetStringField(Key, ExportProperty(Field, Field->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex), Owner));
        }
    }
    return Result;
}

static TSharedRef<FJsonObject> StructObjectReferences(const UStruct* Struct, const void* ValuePtr)
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    if (!Struct || !ValuePtr) return Result;
    for (TFieldIterator<FProperty> It(Struct); It; ++It)
    {
        const FObjectPropertyBase* Field = CastField<FObjectPropertyBase>(*It);
        if (!Field || !ShouldInspectProperty(Field)) continue;
        UObject* Target = Field->GetObjectPropertyValue(Field->ContainerPtrToValuePtr<void>(ValuePtr));
        if (Target) Result->SetStringField(Field->GetName(), Target->GetPathName());
    }
    return Result;
}

static TArray<UObject*> ObjectArray(UObject* Object, const TCHAR* Name)
{
    TArray<UObject*> Result;
    if (!Object) return Result;
    const FArrayProperty* Array = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(FName(Name)));
    if (!Array) return Result;
    const FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Array->Inner);
    if (!Inner) return Result;
    FScriptArrayHelper Helper(Array, Array->ContainerPtrToValuePtr<void>(Object));
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        if (UObject* Value = Inner->GetObjectPropertyValue(Helper.GetRawPtr(Index))) Result.Add(Value);
    }
    return Result;
}

static TArray<TSharedPtr<FJsonValue>> ObjectArrayJson(UObject* Object, const TCHAR* Name)
{
    TArray<TSharedPtr<FJsonValue>> Result;
    for (UObject* Value : ObjectArray(Object, Name))
    {
        TSharedRef<FJsonObject> Entry = MakeShared<FJsonObject>();
        Entry->SetStringField(TEXT("path"), Value->GetPathName());
        Entry->SetStringField(TEXT("class"), Value->GetClass()->GetPathName());
        Result.Add(MakeShared<FJsonValueObject>(Entry));
    }
    return Result;
}

static TSharedRef<FJsonObject> SelectedObjectFields(UObject* Object, const TCHAR* const* Names, int32 Count)
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    if (!Object) return Result;
    for (int32 Index = 0; Index < Count; ++Index)
    {
        const TCHAR* Name = Names[Index];
        const FProperty* Property = Object->GetClass()->FindPropertyByName(FName(Name));
        if (!Property || !ShouldInspectProperty(Property)) continue;
        Result->SetStringField(Name, ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(Object), Object));
    }
    return Result;
}

static bool WritePropertyRows(
    UObject* Object,
    const FString& OwnerPath,
    const FString& Family,
    const FString& Role,
    FJsonlWriter& Writer,
    FCounts& Counts,
    bool bAllDirectProperties)
{
    if (!Object) return true;
    for (TFieldIterator<FProperty> It(Object->GetClass()); It; ++It)
    {
        const FProperty* Property = *It;
        if (!ShouldInspectProperty(Property)) continue;
        if (!bAllDirectProperties &&
            CastField<FArrayProperty>(Property) == nullptr &&
            CastField<FMapProperty>(Property) == nullptr &&
            CastField<FObjectPropertyBase>(Property) == nullptr &&
            CastField<FStructProperty>(Property) == nullptr)
        {
            continue;
        }
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("family"), Family);
        Row->SetStringField(TEXT("role"), Role);
        Row->SetStringField(TEXT("owner_path"), OwnerPath);
        Row->SetStringField(TEXT("owner_class"), Object->GetClass()->GetPathName());
        Row->SetStringField(TEXT("property_name"), Property->GetName());
        Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
        Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
        const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
        Row->SetStringField(TEXT("value"), ExportProperty(Property, ValuePtr, Object));
        if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
        {
            UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr);
            Row->SetStringField(TEXT("target_path"), ObjectPath(Target));
            Row->SetStringField(TEXT("target_class"), ObjectClass(Target));
        }
        if (const FArrayProperty* Array = CastField<FArrayProperty>(Property))
        {
            FScriptArrayHelper Helper(Array, const_cast<void*>(ValuePtr));
            Row->SetNumberField(TEXT("array_count"), Helper.Num());
        }
        if (!Writer.Write(Row)) return false;
        ++Counts.PropertyRows;
    }
    return true;
}

static bool WriteLandscapeComponent(
    UObject* Root,
    UObject* Component,
    int32 ComponentIndex,
    FWriters& Writers,
    FCounts& Counts)
{
    const FString RootPath = Root->GetPathName();
    const FString ComponentPath = Component->GetPathName();
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("landscape_path"), RootPath);
    Row->SetStringField(TEXT("landscape_class"), Root->GetClass()->GetPathName());
    Row->SetStringField(TEXT("component_path"), ComponentPath);
    Row->SetStringField(TEXT("component_class"), Component->GetClass()->GetPathName());
    Row->SetNumberField(TEXT("component_index"), ComponentIndex);
    Row->SetObjectField(
        TEXT("fields"),
        SelectedObjectFields(Component, LandscapeComponentProperties, UE_ARRAY_COUNT(LandscapeComponentProperties)));
    Row->SetArrayField(TEXT("weightmap_textures"), ObjectArrayJson(Component, TEXT("WeightmapTextures")));
    UObject* Heightmap = ObjectField(Component, TEXT("HeightmapTexture"));
    Row->SetStringField(TEXT("heightmap_texture_path"), ObjectPath(Heightmap));
    Row->SetStringField(TEXT("heightmap_texture_class"), ObjectClass(Heightmap));
    if (!Writers.LandscapeComponents.Write(Row)) return false;
    ++Counts.LandscapeComponents;

    const FArrayProperty* Allocations = CastField<FArrayProperty>(
        Component->GetClass()->FindPropertyByName(TEXT("WeightmapLayerAllocations")));
    if (!Allocations) return true;
    const FStructProperty* AllocationStruct = CastField<FStructProperty>(Allocations->Inner);
    if (!AllocationStruct || !AllocationStruct->Struct) return true;
    FScriptArrayHelper Helper(Allocations, Allocations->ContainerPtrToValuePtr<void>(Component));
    for (int32 AllocationIndex = 0; AllocationIndex < Helper.Num(); ++AllocationIndex)
    {
        const void* Value = Helper.GetRawPtr(AllocationIndex);
        TSharedRef<FJsonObject> Allocation = MakeShared<FJsonObject>();
        Allocation->SetStringField(TEXT("landscape_path"), RootPath);
        Allocation->SetStringField(TEXT("component_path"), ComponentPath);
        Allocation->SetNumberField(TEXT("component_index"), ComponentIndex);
        Allocation->SetNumberField(TEXT("allocation_index"), AllocationIndex);
        Allocation->SetStringField(TEXT("struct_type"), AllocationStruct->Struct->GetPathName());
        Allocation->SetObjectField(TEXT("fields"), StructFields(AllocationStruct->Struct, Value, Component));
        Allocation->SetObjectField(TEXT("object_references"), StructObjectReferences(AllocationStruct->Struct, Value));
        Allocation->SetStringField(TEXT("raw_value"), ExportProperty(Allocations->Inner, Value, Component));
        if (!Writers.LandscapeAllocations.Write(Allocation)) return false;
        ++Counts.LandscapeWeightmapAllocations;
    }
    return true;
}

static bool WriteLandscapeRoot(const FAssetData& Asset, UObject* Root, FWriters& Writers, FCounts& Counts)
{
    const FString Path = Root->GetPathName();
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("landscape_path"), Path);
    Row->SetStringField(TEXT("class_path"), Root->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetObjectField(
        TEXT("fields"),
        SelectedObjectFields(Root, LandscapeRootProperties, UE_ARRAY_COUNT(LandscapeRootProperties)));
    Row->SetNumberField(TEXT("landscape_component_count"), ArrayCount(Root, TEXT("LandscapeComponents")));
    Row->SetNumberField(TEXT("collision_component_count"), ArrayCount(Root, TEXT("CollisionComponents")));
    Row->SetStringField(TEXT("landscape_material_path"), ObjectPath(ObjectField(Root, TEXT("LandscapeMaterial"))));
    Row->SetStringField(TEXT("landscape_hole_material_path"), ObjectPath(ObjectField(Root, TEXT("LandscapeHoleMaterial"))));
    if (!Writers.LandscapeRoots.Write(Row)) return false;
    ++Counts.LandscapeRoots;

    const TArray<UObject*> Components = ObjectArray(Root, TEXT("LandscapeComponents"));
    for (int32 Index = 0; Index < Components.Num(); ++Index)
    {
        if (!WriteLandscapeComponent(Root, Components[Index], Index, Writers, Counts)) return false;
    }
    return true;
}

static bool WriteLandscapeLayerInfo(const FAssetData& Asset, UObject* Object, FWriters& Writers, FCounts& Counts)
{
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("layer_info_path"), Object->GetPathName());
    Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("layer_name"), ObjectFieldText(Object, TEXT("LayerName")));
    Row->SetStringField(TEXT("physical_material_path"), ObjectPath(ObjectField(Object, TEXT("PhysMaterial"))));
    Row->SetStringField(TEXT("no_weight_blend"), ObjectFieldText(Object, TEXT("bNoWeightBlend")));
    Row->SetStringField(TEXT("hardness"), ObjectFieldText(Object, TEXT("Hardness")));
    if (!Writers.LandscapeLayerInfos.Write(Row)) return false;
    ++Counts.LandscapeLayerInfos;
    return WritePropertyRows(Object, Object->GetPathName(), TEXT("landscape"), TEXT("layer_info"), Writers.Properties, Counts, true);
}

static bool WriteLandscapeGrassType(const FAssetData& Asset, UObject* Object, FWriters& Writers, FCounts& Counts)
{
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("grass_type_path"), Object->GetPathName());
    Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("enable_density_scaling"), ObjectFieldText(Object, TEXT("bEnableDensityScaling")));
    Row->SetNumberField(TEXT("grass_variety_count"), ArrayCount(Object, TEXT("GrassVarieties")));
    if (!Writers.LandscapeGrassTypes.Write(Row)) return false;
    ++Counts.LandscapeGrassTypes;

    const FArrayProperty* Varieties = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(TEXT("GrassVarieties")));
    const FStructProperty* VarietyStruct = Varieties ? CastField<FStructProperty>(Varieties->Inner) : nullptr;
    if (Varieties && VarietyStruct && VarietyStruct->Struct)
    {
        FScriptArrayHelper Helper(Varieties, Varieties->ContainerPtrToValuePtr<void>(Object));
        for (int32 Index = 0; Index < Helper.Num(); ++Index)
        {
            const void* Value = Helper.GetRawPtr(Index);
            TSharedRef<FJsonObject> Variety = MakeShared<FJsonObject>();
            Variety->SetStringField(TEXT("grass_type_path"), Object->GetPathName());
            Variety->SetNumberField(TEXT("variety_index"), Index);
            Variety->SetStringField(TEXT("struct_type"), VarietyStruct->Struct->GetPathName());
            Variety->SetObjectField(TEXT("fields"), StructFields(VarietyStruct->Struct, Value, Object));
            Variety->SetObjectField(TEXT("object_references"), StructObjectReferences(VarietyStruct->Struct, Value));
            Variety->SetStringField(TEXT("raw_value"), ExportProperty(Varieties->Inner, Value, Object));
            if (!Writers.LandscapeGrassVarieties.Write(Variety)) return false;
            ++Counts.LandscapeGrassVarieties;
        }
    }
    return WritePropertyRows(Object, Object->GetPathName(), TEXT("landscape"), TEXT("grass_type"), Writers.Properties, Counts, true);
}

static bool WriteFoliageType(const FAssetData& Asset, UObject* Object, FWriters& Writers, FCounts& Counts)
{
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("foliage_type_path"), Object->GetPathName());
    Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    UObject* Mesh = ObjectField(Object, TEXT("Mesh"));
    Row->SetStringField(TEXT("mesh_path"), ObjectPath(Mesh));
    Row->SetStringField(TEXT("mesh_class"), ObjectClass(Mesh));
    Row->SetStringField(TEXT("component_class"), ObjectFieldText(Object, TEXT("ComponentClass")));
    Row->SetStringField(TEXT("include_in_hlod"), ObjectFieldText(Object, TEXT("bIncludeInHLOD")));
    Row->SetStringField(TEXT("density"), ObjectFieldText(Object, TEXT("Density")));
    Row->SetStringField(TEXT("radius"), ObjectFieldText(Object, TEXT("Radius")));
    Row->SetStringField(TEXT("align_to_normal"), ObjectFieldText(Object, TEXT("AlignToNormal")));
    Row->SetStringField(TEXT("cull_distance"), ObjectFieldText(Object, TEXT("CullDistance")));
    if (!Writers.FoliageTypes.Write(Row)) return false;
    ++Counts.FoliageTypes;
    return WritePropertyRows(Object, Object->GetPathName(), TEXT("foliage"), TEXT("foliage_type"), Writers.Properties, Counts, true);
}

static const FMapProperty* FindFoliageInfoMap(UObject* Actor)
{
    if (!Actor) return nullptr;
    if (const FMapProperty* Exact = CastField<FMapProperty>(Actor->GetClass()->FindPropertyByName(TEXT("FoliageInfos"))))
        return Exact;
    for (TFieldIterator<FProperty> It(Actor->GetClass()); It; ++It)
    {
        const FMapProperty* Map = CastField<FMapProperty>(*It);
        if (!Map) continue;
        const FObjectPropertyBase* KeyObject = CastField<FObjectPropertyBase>(Map->KeyProp);
        if (!KeyObject || !KeyObject->PropertyClass) continue;
        if (KeyObject->PropertyClass->GetPathName().StartsWith(TEXT("/Script/Foliage.FoliageType"), ESearchCase::CaseSensitive))
            return Map;
    }
    return nullptr;
}

static bool WriteFoliageActor(const FAssetData& Asset, UObject* Actor, FWriters& Writers, FCounts& Counts)
{
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("foliage_actor_path"), Actor->GetPathName());
    Row->SetStringField(TEXT("class_path"), Actor->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());

    const FMapProperty* Map = FindFoliageInfoMap(Actor);
    Row->SetStringField(TEXT("foliage_info_property"), Map ? Map->GetName() : FString());
    int32 InfoCount = 0;
    if (Map)
    {
        FScriptMapHelper Helper(Map, Map->ContainerPtrToValuePtr<void>(Actor));
        InfoCount = Helper.Num();
    }
    Row->SetNumberField(TEXT("foliage_info_count"), InfoCount);
    if (!Writers.FoliageActors.Write(Row)) return false;
    ++Counts.FoliageActors;

    if (!Map) return true;
    const FObjectPropertyBase* KeyObject = CastField<FObjectPropertyBase>(Map->KeyProp);
    const FStructProperty* InfoStruct = CastField<FStructProperty>(Map->ValueProp);
    if (!KeyObject || !InfoStruct || !InfoStruct->Struct)
    {
        ++Counts.FoliageInfoMapsOpaque;
        return true;
    }

    FScriptMapHelper Helper(Map, Map->ContainerPtrToValuePtr<void>(Actor));
    for (int32 MapIndex = 0; MapIndex < Helper.GetMaxIndex(); ++MapIndex)
    {
        if (!Helper.IsValidIndex(MapIndex)) continue;
        UObject* Type = KeyObject->GetObjectPropertyValue(Helper.GetKeyPtr(MapIndex));
        const void* InfoValue = Helper.GetValuePtr(MapIndex);
        TSharedRef<FJsonObject> Info = MakeShared<FJsonObject>();
        Info->SetStringField(TEXT("foliage_actor_path"), Actor->GetPathName());
        Info->SetNumberField(TEXT("map_index"), MapIndex);
        Info->SetStringField(TEXT("foliage_type_path"), ObjectPath(Type));
        Info->SetStringField(TEXT("foliage_type_class"), ObjectClass(Type));
        Info->SetStringField(TEXT("info_struct"), InfoStruct->Struct->GetPathName());
        Info->SetObjectField(TEXT("fields"), StructFields(InfoStruct->Struct, InfoValue, Actor));
        Info->SetObjectField(TEXT("object_references"), StructObjectReferences(InfoStruct->Struct, InfoValue));

        const FArrayProperty* Instances = CastField<FArrayProperty>(InfoStruct->Struct->FindPropertyByName(TEXT("Instances")));
        const FStructProperty* InstanceStruct = Instances ? CastField<FStructProperty>(Instances->Inner) : nullptr;
        int32 InstanceCount = 0;
        if (Instances)
        {
            FScriptArrayHelper InstancesHelper(Instances, Instances->ContainerPtrToValuePtr<void>(const_cast<void*>(InfoValue)));
            InstanceCount = InstancesHelper.Num();
            if (InstanceStruct && InstanceStruct->Struct)
            {
                for (int32 InstanceIndex = 0; InstanceIndex < InstancesHelper.Num(); ++InstanceIndex)
                {
                    const void* InstanceValue = InstancesHelper.GetRawPtr(InstanceIndex);
                    TSharedRef<FJsonObject> Instance = MakeShared<FJsonObject>();
                    Instance->SetStringField(TEXT("foliage_actor_path"), Actor->GetPathName());
                    Instance->SetStringField(TEXT("foliage_type_path"), ObjectPath(Type));
                    Instance->SetNumberField(TEXT("map_index"), MapIndex);
                    Instance->SetNumberField(TEXT("instance_index"), InstanceIndex);
                    Instance->SetStringField(TEXT("instance_struct"), InstanceStruct->Struct->GetPathName());
                    Instance->SetObjectField(TEXT("fields"), StructFields(InstanceStruct->Struct, InstanceValue, Actor));
                    Instance->SetObjectField(TEXT("object_references"), StructObjectReferences(InstanceStruct->Struct, InstanceValue));
                    Instance->SetStringField(TEXT("raw_value"), ExportProperty(Instances->Inner, InstanceValue, Actor));
                    if (!Writers.FoliageInstances.Write(Instance)) return false;
                    ++Counts.FoliageInstances;
                }
            }
        }
        Info->SetNumberField(TEXT("instance_count"), InstanceCount);
        Info->SetBoolField(TEXT("instances_reflected_as_struct_array"), Instances && InstanceStruct && InstanceStruct->Struct);
        if (!Writers.FoliageActorTypeInfos.Write(Info)) return false;
        ++Counts.FoliageActorTypeInfos;
    }
    return true;
}

static bool WriteHLODLayer(const FAssetData& Asset, UObject* Object, FWriters& Writers, FCounts& Counts)
{
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("hlod_layer_path"), Object->GetPathName());
    Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    static const TCHAR* Names[] = {
        TEXT("LayerType"), TEXT("CellSize"), TEXT("LoadingRange"), TEXT("ParentLayer"),
        TEXT("LinkedLayer"), TEXT("HLODBuilderSettings"), TEXT("HLODModifierClass"),
        TEXT("bForceRayTracingFarField")
    };
    Row->SetObjectField(TEXT("fields"), SelectedObjectFields(Object, Names, UE_ARRAY_COUNT(Names)));
    for (const TCHAR* Name : {TEXT("ParentLayer"), TEXT("LinkedLayer"), TEXT("HLODBuilderSettings")})
    {
        UObject* Target = ObjectField(Object, Name);
        Row->SetStringField(FString(Name).ToLower() + TEXT("_path"), ObjectPath(Target));
        Row->SetStringField(FString(Name).ToLower() + TEXT("_class"), ObjectClass(Target));
    }
    if (!Writers.HLODLayers.Write(Row)) return false;
    ++Counts.HLODLayers;
    return WritePropertyRows(Object, Object->GetPathName(), TEXT("hlod"), TEXT("hlod_layer"), Writers.Properties, Counts, true);
}

static bool WriteManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error, bool bIncludeEngine)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetBoolField(TEXT("diagnostic_only"), true);
    Root->SetBoolField(TEXT("semantic_promotion"), false);
    Root->SetBoolField(TEXT("schema_promotion"), false);
    Root->SetBoolField(TEXT("runtime_state_captured"), false);
    Root->SetBoolField(TEXT("generated_geometry_captured"), false);
    Root->SetBoolField(TEXT("render_resources_captured"), false);
    Root->SetBoolField(TEXT("world_runtime_streaming_state_captured"), false);
    Root->SetBoolField(TEXT("maps_loaded"), false);
    Root->SetBoolField(TEXT("include_engine"), bIncludeEngine);
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("capture_scope"), TEXT("exact project Landscape external actors/components/layer allocations/layer-info/grass authoring, FoliageType and reflected editor placement containers, and HLODLayer authored policy; no generated heightfield/render resources, runtime foliage clusters, generated HLOD proxy geometry, or runtime streaming state"));

    TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
    C->SetNumberField(TEXT("registry_candidates"), Counts.RegistryCandidates);
    C->SetNumberField(TEXT("load_failures"), Counts.LoadFailures);
    C->SetNumberField(TEXT("landscape_roots"), Counts.LandscapeRoots);
    C->SetNumberField(TEXT("landscape_components"), Counts.LandscapeComponents);
    C->SetNumberField(TEXT("landscape_weightmap_allocations"), Counts.LandscapeWeightmapAllocations);
    C->SetNumberField(TEXT("landscape_layer_infos"), Counts.LandscapeLayerInfos);
    C->SetNumberField(TEXT("landscape_grass_types"), Counts.LandscapeGrassTypes);
    C->SetNumberField(TEXT("landscape_grass_varieties"), Counts.LandscapeGrassVarieties);
    C->SetNumberField(TEXT("foliage_types"), Counts.FoliageTypes);
    C->SetNumberField(TEXT("foliage_actors"), Counts.FoliageActors);
    C->SetNumberField(TEXT("foliage_actor_type_infos"), Counts.FoliageActorTypeInfos);
    C->SetNumberField(TEXT("foliage_instances"), Counts.FoliageInstances);
    C->SetNumberField(TEXT("foliage_info_maps_opaque"), Counts.FoliageInfoMapsOpaque);
    C->SetNumberField(TEXT("hlod_layers"), Counts.HLODLayers);
    C->SetNumberField(TEXT("property_rows"), Counts.PropertyRows);
    Root->SetObjectField(TEXT("counts"), C);

    static const TCHAR* Names[] = {
        TEXT("landscape_roots.jsonl"), TEXT("landscape_components.jsonl"),
        TEXT("landscape_weightmap_allocations.jsonl"), TEXT("landscape_layer_infos.jsonl"),
        TEXT("landscape_grass_types.jsonl"), TEXT("landscape_grass_varieties.jsonl"),
        TEXT("foliage_types.jsonl"), TEXT("foliage_actors.jsonl"),
        TEXT("foliage_actor_type_infos.jsonl"), TEXT("foliage_instances.jsonl"),
        TEXT("hlod_layers.jsonl"), TEXT("world_geometry_properties.jsonl")
    };
    TArray<TSharedPtr<FJsonValue>> Files;
    for (const TCHAR* Name : Names) Files.Add(MakeShared<FJsonValueString>(Name));
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("world_geometry_capture_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunCapture(const FString& OutputDir, bool bIncludeEngine, FCounts& Counts, FString& OutError)
{
    FWriters Writers;
    if (!Writers.Open(OutputDir))
    {
        OutError = TEXT("could not open world-geometry capture writers");
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.SearchAllAssets(true);

    TArray<FAssetData> Assets;
    Registry.GetAllAssets(Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        return A.GetSoftObjectPath().ToString() < B.GetSoftObjectPath().ToString();
    });

    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    for (const FAssetData& Asset : Assets)
    {
        const FString ClassPath = Asset.AssetClassPath.ToString();
        if (!IsCandidateClass(ClassPath)) continue;
        if (!AssetInScope(Asset, ProjectDir, bIncludeEngine)) continue;
        ++Counts.RegistryCandidates;

        UObject* Object = Asset.GetAsset();
        if (!Object)
        {
            ++Counts.LoadFailures;
            continue;
        }
        const FString LoadedClass = Object->GetClass()->GetPathName();
        if (LoadedClass != ClassPath)
        {
            OutError = TEXT("loaded class mismatch for ") + Asset.GetSoftObjectPath().ToString() +
                TEXT(": registry=") + ClassPath + TEXT(" loaded=") + LoadedClass;
            Writers.Close();
            return false;
        }

        bool bOk = true;
        if (ClassPath == LandscapeClass || ClassPath == LandscapeStreamingProxyClass)
            bOk = WriteLandscapeRoot(Asset, Object, Writers, Counts);
        else if (ClassPath == LandscapeLayerInfoClass)
            bOk = WriteLandscapeLayerInfo(Asset, Object, Writers, Counts);
        else if (ClassPath == LandscapeGrassTypeClass)
            bOk = WriteLandscapeGrassType(Asset, Object, Writers, Counts);
        else if (ClassPath == FoliageTypeClass)
            bOk = WriteFoliageType(Asset, Object, Writers, Counts);
        else if (ClassPath == InstancedFoliageActorClass)
            bOk = WriteFoliageActor(Asset, Object, Writers, Counts);
        else if (ClassPath == HLODLayerClass)
            bOk = WriteHLODLayer(Asset, Object, Writers, Counts);

        if (!bOk)
        {
            OutError = TEXT("failed writing world-geometry candidate ") + Asset.GetSoftObjectPath().ToString();
            Writers.Close();
            return false;
        }
    }

    if (!Writers.Close())
    {
        OutError = TEXT("failed closing one or more world-geometry capture files");
        return false;
    }
    if (Counts.LoadFailures > 0)
    {
        OutError = FString::Printf(TEXT("%lld world-geometry candidate assets failed to load"), Counts.LoadFailures);
        return false;
    }
    return true;
}
}

UUnrealAssetToolWorldGeometryCommandlet::UUnrealAssetToolWorldGeometryCommandlet()
{
    IsClient = false;
    IsEditor = true;
    IsServer = false;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolWorldGeometryCommandlet::Main(const FString& Params)
{
    FString OutputDir;
    FParse::Value(*Params, TEXT("Output="), OutputDir);
    if (OutputDir.IsEmpty()) OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool/world-geometry-native-capture"));
    if (FPaths::IsRelative(OutputDir)) OutputDir = FPaths::ConvertRelativePathToFull(FPaths::ProjectDir(), OutputDir);
    FPaths::NormalizeDirectoryName(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    const bool bIncludeEngine = FParse::Param(*Params, TEXT("IncludeEngine"));
    UnrealAssetToolWorldGeometry::FCounts Counts;
    FString Error;
    const bool bSuccess = UnrealAssetToolWorldGeometry::RunCapture(OutputDir, bIncludeEngine, Counts, Error);
    if (!UnrealAssetToolWorldGeometry::WriteManifest(OutputDir, Counts, bSuccess, Error, bIncludeEngine))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolWorldGeometry: failed to write manifest"));
        return 3;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetToolWorldGeometry: candidates=%lld landscape_roots=%lld components=%lld allocations=%lld layer_infos=%lld grass_types=%lld grass_varieties=%lld foliage_types=%lld foliage_actors=%lld foliage_infos=%lld foliage_instances=%lld opaque_foliage_maps=%lld hlod_layers=%lld properties=%lld"),
        Counts.RegistryCandidates,
        Counts.LandscapeRoots,
        Counts.LandscapeComponents,
        Counts.LandscapeWeightmapAllocations,
        Counts.LandscapeLayerInfos,
        Counts.LandscapeGrassTypes,
        Counts.LandscapeGrassVarieties,
        Counts.FoliageTypes,
        Counts.FoliageActors,
        Counts.FoliageActorTypeInfos,
        Counts.FoliageInstances,
        Counts.FoliageInfoMapsOpaque,
        Counts.HLODLayers,
        Counts.PropertyRows);

    if (!bSuccess)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolWorldGeometry: %s"), *Error);
        return 4;
    }
    return 0;
}
