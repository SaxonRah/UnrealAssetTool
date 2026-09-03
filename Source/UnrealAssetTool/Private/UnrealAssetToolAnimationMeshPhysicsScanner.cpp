#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Dom/JsonObject.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/CommandLine.h"
#include "Misc/CoreDelegates.h"
#include "Misc/DateTime.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolAnimationMeshPhysics
{
static constexpr int32 SchemaVersion = 1;
static constexpr int32 PublicAnimationSchemaVersion = 3;
static constexpr int32 MaxExportChars = 32768;

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
    FJsonlWriter SkeletalMeshes;
    FJsonlWriter SkeletalMeshLods;
    FJsonlWriter SkeletalMeshMaterials;
    FJsonlWriter SkeletalMeshMorphTargets;
    FJsonlWriter SkeletalMeshClothingAssets;
    FJsonlWriter SkeletalMeshClothingConfigs;
    FJsonlWriter PhysicsAssets;
    FJsonlWriter PhysicsBodies;
    FJsonlWriter PhysicsBodyShapes;
    FJsonlWriter PhysicsConstraints;
    FJsonlWriter PhysicsConstraintProfiles;
    FJsonlWriter PhysicsPhysicalAnimationProfiles;
    FJsonlWriter PhysicsCollisionDisablePairs;

    bool Open(const FString& OutputDir)
    {
        return SkeletalMeshes.Open(FPaths::Combine(OutputDir, TEXT("skeletal_meshes.jsonl"))) &&
            SkeletalMeshLods.Open(FPaths::Combine(OutputDir, TEXT("skeletal_mesh_lods.jsonl"))) &&
            SkeletalMeshMaterials.Open(FPaths::Combine(OutputDir, TEXT("skeletal_mesh_materials.jsonl"))) &&
            SkeletalMeshMorphTargets.Open(FPaths::Combine(OutputDir, TEXT("skeletal_mesh_morph_targets.jsonl"))) &&
            SkeletalMeshClothingAssets.Open(FPaths::Combine(OutputDir, TEXT("skeletal_mesh_clothing_assets.jsonl"))) &&
            SkeletalMeshClothingConfigs.Open(FPaths::Combine(OutputDir, TEXT("skeletal_mesh_clothing_configs.jsonl"))) &&
            PhysicsAssets.Open(FPaths::Combine(OutputDir, TEXT("physics_assets.jsonl"))) &&
            PhysicsBodies.Open(FPaths::Combine(OutputDir, TEXT("physics_bodies.jsonl"))) &&
            PhysicsBodyShapes.Open(FPaths::Combine(OutputDir, TEXT("physics_body_shapes.jsonl"))) &&
            PhysicsConstraints.Open(FPaths::Combine(OutputDir, TEXT("physics_constraints.jsonl"))) &&
            PhysicsConstraintProfiles.Open(FPaths::Combine(OutputDir, TEXT("physics_constraint_profiles.jsonl"))) &&
            PhysicsPhysicalAnimationProfiles.Open(FPaths::Combine(OutputDir, TEXT("physics_physical_animation_profiles.jsonl"))) &&
            PhysicsCollisionDisablePairs.Open(FPaths::Combine(OutputDir, TEXT("physics_collision_disable_pairs.jsonl")));
    }

    bool Close()
    {
        bool bOk = true;
        bOk = SkeletalMeshes.Close() && bOk;
        bOk = SkeletalMeshLods.Close() && bOk;
        bOk = SkeletalMeshMaterials.Close() && bOk;
        bOk = SkeletalMeshMorphTargets.Close() && bOk;
        bOk = SkeletalMeshClothingAssets.Close() && bOk;
        bOk = SkeletalMeshClothingConfigs.Close() && bOk;
        bOk = PhysicsAssets.Close() && bOk;
        bOk = PhysicsBodies.Close() && bOk;
        bOk = PhysicsBodyShapes.Close() && bOk;
        bOk = PhysicsConstraints.Close() && bOk;
        bOk = PhysicsConstraintProfiles.Close() && bOk;
        bOk = PhysicsPhysicalAnimationProfiles.Close() && bOk;
        bOk = PhysicsCollisionDisablePairs.Close() && bOk;
        return bOk;
    }
};

struct FCounts
{
    int64 RegistryCandidates = 0;
    int64 SkeletalMeshes = 0;
    int64 SkeletalMeshLods = 0;
    int64 SkeletalMeshMaterials = 0;
    int64 SkeletalMeshMorphTargets = 0;
    int64 SkeletalMeshClothingAssets = 0;
    int64 SkeletalMeshClothingConfigs = 0;
    int64 PhysicsAssets = 0;
    int64 PhysicsBodies = 0;
    int64 PhysicsBodyShapes = 0;
    int64 PhysicsConstraints = 0;
    int64 PhysicsConstraintProfiles = 0;
    int64 PhysicsPhysicalAnimationProfiles = 0;
    int64 PhysicsCollisionDisablePairs = 0;
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
    if (Text.Len() > MaxExportChars)
    {
        Text.LeftInline(MaxExportChars, EAllowShrinking::No);
    }
    return Text;
}

static FString ExportObjectProperty(UObject* Object, const TCHAR* Name)
{
    if (!Object) return FString();
    const FProperty* Property = Object->GetClass()->FindPropertyByName(FName(Name));
    if (!Property || !ShouldInspectProperty(Property)) return FString();
    return ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(Object), Object);
}

static FString ReferencePath(UObject* Object, const TCHAR* Name)
{
    if (!Object) return FString();
    const FProperty* Property = Object->GetClass()->FindPropertyByName(FName(Name));
    if (!Property) return FString();
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Object);
    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        if (UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr)) return Target->GetPathName();
    }
    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* Ptr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (Ptr && !Ptr->IsNull()) return Ptr->ToSoftObjectPath().ToString();
    }
    return FString();
}

static FString AssetTag(const FAssetData& Asset, const TCHAR* Name)
{
    FString Value;
    Asset.GetTagValue(FName(Name), Value);
    return Value;
}

static int32 ParseIntTag(const FAssetData& Asset, const TCHAR* Name)
{
    const FString Value = AssetTag(Asset, Name);
    return Value.IsEmpty() ? 0 : FCString::Atoi(*Value);
}

static TSharedRef<FJsonObject> StructFields(const UStruct* Struct, const void* ValuePtr, UObject* Owner, const TSet<FName>& Excluded = {})
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    if (!Struct || !ValuePtr) return Result;
    for (TFieldIterator<FProperty> It(Struct); It; ++It)
    {
        const FProperty* Field = *It;
        if (!ShouldInspectProperty(Field) || Excluded.Contains(Field->GetFName())) continue;
        for (int32 StaticIndex = 0; StaticIndex < Field->ArrayDim; ++StaticIndex)
        {
            FString Key = Field->GetName();
            if (Field->ArrayDim > 1) Key += FString::Printf(TEXT("[%d]"), StaticIndex);
            Result->SetStringField(Key, ExportProperty(Field, Field->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex), Owner));
        }
    }
    return Result;
}

static TSharedRef<FJsonObject> ObjectFields(UObject* Object, const TSet<FName>& Excluded = {})
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    if (!Object) return Result;
    TSet<FString> Seen;
    for (UClass* Class = Object->GetClass(); Class && Class != UObject::StaticClass(); Class = Class->GetSuperClass())
    {
        for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
        {
            const FProperty* Property = *It;
            if (!ShouldInspectProperty(Property) || Excluded.Contains(Property->GetFName())) continue;
            const FString Identity = Class->GetPathName() + TEXT("::") + Property->GetName();
            if (Seen.Contains(Identity)) continue;
            Seen.Add(Identity);
            for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
            {
                FString Key = Property->GetName();
                if (Property->ArrayDim > 1) Key += FString::Printf(TEXT("[%d]"), StaticIndex);
                Result->SetStringField(Key, ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(Object, StaticIndex), Object));
            }
        }
    }
    return Result;
}

static FString StructFieldText(const UStruct* Struct, const void* ValuePtr, const TCHAR* Name, UObject* Owner)
{
    if (!Struct || !ValuePtr) return FString();
    const FProperty* Field = Struct->FindPropertyByName(FName(Name));
    if (!Field || !ShouldInspectProperty(Field)) return FString();
    return ExportProperty(Field, Field->ContainerPtrToValuePtr<void>(ValuePtr), Owner);
}

static UObject* StructObjectField(const UStruct* Struct, const void* ValuePtr, const TCHAR* Name)
{
    if (!Struct || !ValuePtr) return nullptr;
    const FObjectPropertyBase* Field = CastField<FObjectPropertyBase>(Struct->FindPropertyByName(FName(Name)));
    if (!Field) return nullptr;
    return Field->GetObjectPropertyValue(Field->ContainerPtrToValuePtr<void>(ValuePtr));
}

static bool WriteNameArray(UObject* Object, const TCHAR* PropertyName, const FString& AssetPath, FJsonlWriter& Writer, int64& Count)
{
    if (!Object) return true;
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Object->GetClass()->FindPropertyByName(FName(PropertyName)));
    if (!ArrayProperty) return true;
    const void* ArrayPtr = ArrayProperty->ContainerPtrToValuePtr<void>(Object);
    FScriptArrayHelper Helper(ArrayProperty, ArrayPtr);
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("physics_asset_path"), AssetPath);
        Row->SetNumberField(TEXT("profile_index"), Index);
        Row->SetStringField(TEXT("profile_name"), ExportProperty(ArrayProperty->Inner, Helper.GetRawPtr(Index), Object));
        if (!Writer.Write(Row)) return false;
        ++Count;
    }
    return true;
}

static bool WriteLods(UObject* Mesh, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    const FArrayProperty* SourceModels = CastField<FArrayProperty>(Mesh->GetClass()->FindPropertyByName(TEXT("SourceModels")));
    if (!SourceModels) return true;
    const FStructProperty* SourceModelStruct = CastField<FStructProperty>(SourceModels->Inner);
    if (!SourceModelStruct || !SourceModelStruct->Struct) return true;
    FScriptArrayHelper Helper(SourceModels, SourceModels->ContainerPtrToValuePtr<void>(Mesh));
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Value = Helper.GetRawPtr(Index);
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("skeletal_mesh_path"), AssetPath);
        Row->SetNumberField(TEXT("lod_index"), Index);
        Row->SetStringField(TEXT("source_model_struct"), SourceModelStruct->Struct->GetPathName());
        Row->SetStringField(TEXT("lod_model_id"), StructFieldText(SourceModelStruct->Struct, Value, TEXT("LODModelId"), Mesh));
        Row->SetStringField(TEXT("imported_with_base_mesh"), StructFieldText(SourceModelStruct->Struct, Value, TEXT("bImportedWithBaseMesh"), Mesh));
        Row->SetStringField(TEXT("morph_target_position_error_tolerance"), StructFieldText(SourceModelStruct->Struct, Value, TEXT("MorphTargetPositionErrorTolerance"), Mesh));

        if (const FStructProperty* Build = CastField<FStructProperty>(SourceModelStruct->Struct->FindPropertyByName(TEXT("BuildSettings"))))
        {
            const void* BuildValue = Build->ContainerPtrToValuePtr<void>(Value);
            Row->SetObjectField(TEXT("build_settings"), StructFields(Build->Struct, BuildValue, Mesh));
        }
        if (const FStructProperty* Reduction = CastField<FStructProperty>(SourceModelStruct->Struct->FindPropertyByName(TEXT("ReductionSettings"))))
        {
            const void* ReductionValue = Reduction->ContainerPtrToValuePtr<void>(Value);
            Row->SetObjectField(TEXT("reduction_settings"), StructFields(Reduction->Struct, ReductionValue, Mesh));
        }
        if (!Writers.SkeletalMeshLods.Write(Row)) return false;
        ++Counts.SkeletalMeshLods;
    }
    return true;
}

static bool WriteMaterials(UObject* Mesh, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    const FArrayProperty* Materials = CastField<FArrayProperty>(Mesh->GetClass()->FindPropertyByName(TEXT("Materials")));
    if (!Materials) return true;
    const FStructProperty* MaterialStruct = CastField<FStructProperty>(Materials->Inner);
    if (!MaterialStruct || !MaterialStruct->Struct) return true;
    FScriptArrayHelper Helper(Materials, Materials->ContainerPtrToValuePtr<void>(Mesh));
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Value = Helper.GetRawPtr(Index);
        UObject* Material = StructObjectField(MaterialStruct->Struct, Value, TEXT("MaterialInterface"));
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("skeletal_mesh_path"), AssetPath);
        Row->SetNumberField(TEXT("material_index"), Index);
        Row->SetStringField(TEXT("material_path"), Material ? Material->GetPathName() : FString());
        Row->SetStringField(TEXT("material_class"), Material ? Material->GetClass()->GetPathName() : FString());
        Row->SetStringField(TEXT("material_slot_name"), StructFieldText(MaterialStruct->Struct, Value, TEXT("MaterialSlotName"), Mesh));
        Row->SetStringField(TEXT("imported_material_slot_name"), StructFieldText(MaterialStruct->Struct, Value, TEXT("ImportedMaterialSlotName"), Mesh));
        if (!Writers.SkeletalMeshMaterials.Write(Row)) return false;
        ++Counts.SkeletalMeshMaterials;
    }
    return true;
}

static bool WriteObjectArray(UObject* Owner, const TCHAR* PropertyName, const FString& AssetPath, FJsonlWriter& Writer, int64& Count, const TCHAR* IndexName, const TCHAR* PathName)
{
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Owner->GetClass()->FindPropertyByName(FName(PropertyName)));
    if (!ArrayProperty) return true;
    const FObjectPropertyBase* InnerObject = CastField<FObjectPropertyBase>(ArrayProperty->Inner);
    if (!InnerObject) return true;
    FScriptArrayHelper Helper(ArrayProperty, ArrayProperty->ContainerPtrToValuePtr<void>(Owner));
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        UObject* Object = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
        if (!Object) continue;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("skeletal_mesh_path"), AssetPath);
        Row->SetNumberField(IndexName, Index);
        Row->SetStringField(PathName, Object->GetPathName());
        Row->SetStringField(TEXT("object_name"), Object->GetName());
        Row->SetStringField(TEXT("class_path"), Object->GetClass()->GetPathName());
        if (!Writer.Write(Row)) return false;
        ++Count;
    }
    return true;
}

static bool WriteClothing(UObject* Mesh, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Mesh->GetClass()->FindPropertyByName(TEXT("MeshClothingAssets")));
    if (!ArrayProperty) return true;
    const FObjectPropertyBase* InnerObject = CastField<FObjectPropertyBase>(ArrayProperty->Inner);
    if (!InnerObject) return true;
    FScriptArrayHelper Helper(ArrayProperty, ArrayProperty->ContainerPtrToValuePtr<void>(Mesh));
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        UObject* Clothing = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
        if (!Clothing) continue;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("skeletal_mesh_path"), AssetPath);
        Row->SetNumberField(TEXT("clothing_index"), Index);
        Row->SetStringField(TEXT("clothing_asset_path"), Clothing->GetPathName());
        Row->SetStringField(TEXT("clothing_asset_name"), Clothing->GetName());
        Row->SetStringField(TEXT("class_path"), Clothing->GetClass()->GetPathName());
        Row->SetStringField(TEXT("physics_asset_path"), ReferencePath(Clothing, TEXT("PhysicsAsset")));
        if (!Writers.SkeletalMeshClothingAssets.Write(Row)) return false;
        ++Counts.SkeletalMeshClothingAssets;

        TArray<UObject*> Nested;
        GetObjectsWithOuter(Clothing, Nested, EGetObjectsFlags::IncludeNestedObjects);
        Nested.Sort([](const UObject& A, const UObject& B)
        {
            return FCString::Strcmp(*A.GetPathName(), *B.GetPathName()) < 0;
        });
        int32 ConfigIndex = 0;
        for (UObject* Object : Nested)
        {
            if (!Object) continue;
            const FString ClassPath = Object->GetClass()->GetPathName();
            if (ClassPath != TEXT("/Script/ChaosCloth.ChaosClothConfig") &&
                ClassPath != TEXT("/Script/ChaosCloth.ChaosClothSharedSimConfig"))
            {
                continue;
            }
            TSharedRef<FJsonObject> ConfigRow = MakeShared<FJsonObject>();
            ConfigRow->SetStringField(TEXT("skeletal_mesh_path"), AssetPath);
            ConfigRow->SetStringField(TEXT("clothing_asset_path"), Clothing->GetPathName());
            ConfigRow->SetNumberField(TEXT("config_index"), ConfigIndex++);
            ConfigRow->SetStringField(TEXT("config_path"), Object->GetPathName());
            ConfigRow->SetStringField(TEXT("config_class"), ClassPath);
            ConfigRow->SetObjectField(TEXT("properties"), ObjectFields(Object));
            if (!Writers.SkeletalMeshClothingConfigs.Write(ConfigRow)) return false;
            ++Counts.SkeletalMeshClothingConfigs;
        }
    }
    return true;
}

static bool WriteSkeletalMesh(UObject* Mesh, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("skeletal_mesh_path"), AssetPath);
    Row->SetStringField(TEXT("class_path"), Mesh->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("skeleton_path"), ReferencePath(Mesh, TEXT("Skeleton")));
    Row->SetStringField(TEXT("physics_asset_path"), ReferencePath(Mesh, TEXT("PhysicsAsset")));
    Row->SetStringField(TEXT("shadow_physics_asset_path"), ReferencePath(Mesh, TEXT("ShadowPhysicsAsset")));
    Row->SetStringField(TEXT("lod_settings_path"), ReferencePath(Mesh, TEXT("LODSettings")));
    Row->SetNumberField(TEXT("bone_count"), ParseIntTag(Asset, TEXT("Bones")));
    Row->SetNumberField(TEXT("lod_count"), ParseIntTag(Asset, TEXT("LODs")));
    Row->SetNumberField(TEXT("triangle_count"), ParseIntTag(Asset, TEXT("Triangles")));
    Row->SetNumberField(TEXT("vertex_count"), ParseIntTag(Asset, TEXT("Vertices")));
    Row->SetNumberField(TEXT("morph_target_tag_count"), ParseIntTag(Asset, TEXT("MorphTargets")));
    Row->SetNumberField(TEXT("skin_weight_profile_tag_count"), ParseIntTag(Asset, TEXT("SkinWeightProfiles")));
    Row->SetStringField(TEXT("nanite_enabled"), AssetTag(Asset, TEXT("NaniteEnabled")));
    Row->SetNumberField(TEXT("nanite_triangle_count"), ParseIntTag(Asset, TEXT("NaniteTriangles")));
    Row->SetNumberField(TEXT("nanite_vertex_count"), ParseIntTag(Asset, TEXT("NaniteVertices")));

    auto ArrayCount = [Mesh](const TCHAR* Name) -> int32
    {
        const FArrayProperty* Array = CastField<FArrayProperty>(Mesh->GetClass()->FindPropertyByName(FName(Name)));
        if (!Array) return 0;
        FScriptArrayHelper Helper(Array, Array->ContainerPtrToValuePtr<void>(Mesh));
        return Helper.Num();
    };
    Row->SetNumberField(TEXT("material_count"), ArrayCount(TEXT("Materials")));
    Row->SetNumberField(TEXT("morph_target_count"), ArrayCount(TEXT("MorphTargets")));
    Row->SetNumberField(TEXT("clothing_asset_count"), ArrayCount(TEXT("MeshClothingAssets")));
    Row->SetNumberField(TEXT("mesh_socket_count"), ArrayCount(TEXT("Sockets")));
    Row->SetNumberField(TEXT("source_model_count"), ArrayCount(TEXT("SourceModels")));
    Row->SetStringField(TEXT("cloth_lod_bias_mode"), ExportObjectProperty(Mesh, TEXT("ClothLODBiasMode")));
    if (!Writers.SkeletalMeshes.Write(Row)) return false;
    ++Counts.SkeletalMeshes;

    if (!WriteLods(Mesh, AssetPath, Writers, Counts)) return false;
    if (!WriteMaterials(Mesh, AssetPath, Writers, Counts)) return false;
    if (!WriteObjectArray(Mesh, TEXT("MorphTargets"), AssetPath, Writers.SkeletalMeshMorphTargets, Counts.SkeletalMeshMorphTargets, TEXT("morph_index"), TEXT("morph_target_path"))) return false;
    if (!WriteClothing(Mesh, AssetPath, Writers, Counts)) return false;
    return true;
}

static bool WriteBodyShapes(UObject* Body, const FString& AssetPath, int32 BodyIndex, FWriters& Writers, FCounts& Counts)
{
    const FStructProperty* AggGeom = CastField<FStructProperty>(Body->GetClass()->FindPropertyByName(TEXT("AggGeom")));
    if (!AggGeom || !AggGeom->Struct) return true;
    const void* AggValue = AggGeom->ContainerPtrToValuePtr<void>(Body);
    static const TCHAR* ShapeArrays[] = {
        TEXT("SphereElems"), TEXT("BoxElems"), TEXT("SphylElems"), TEXT("ConvexElems"),
        TEXT("TaperedCapsuleElems"), TEXT("LevelSetElems"), TEXT("SkinnedLevelSetElems")
    };
    for (const TCHAR* ShapeArrayName : ShapeArrays)
    {
        const FArrayProperty* Shapes = CastField<FArrayProperty>(AggGeom->Struct->FindPropertyByName(FName(ShapeArrayName)));
        if (!Shapes) continue;
        const FStructProperty* ShapeStruct = CastField<FStructProperty>(Shapes->Inner);
        FScriptArrayHelper Helper(Shapes, Shapes->ContainerPtrToValuePtr<void>(AggValue));
        for (int32 ShapeIndex = 0; ShapeIndex < Helper.Num(); ++ShapeIndex)
        {
            const void* ShapeValue = Helper.GetRawPtr(ShapeIndex);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("physics_asset_path"), AssetPath);
            Row->SetNumberField(TEXT("body_index"), BodyIndex);
            Row->SetStringField(TEXT("body_path"), Body->GetPathName());
            Row->SetStringField(TEXT("shape_type"), ShapeArrayName);
            Row->SetNumberField(TEXT("shape_index"), ShapeIndex);
            Row->SetStringField(TEXT("shape_struct"), ShapeStruct && ShapeStruct->Struct ? ShapeStruct->Struct->GetPathName() : FString());
            if (ShapeStruct && ShapeStruct->Struct)
            {
                Row->SetObjectField(TEXT("fields"), StructFields(ShapeStruct->Struct, ShapeValue, Body));
            }
            Row->SetStringField(TEXT("raw_value"), ExportProperty(Shapes->Inner, ShapeValue, Body));
            if (!Writers.PhysicsBodyShapes.Write(Row)) return false;
            ++Counts.PhysicsBodyShapes;
        }
    }
    return true;
}

static bool WriteBodies(UObject* PhysicsAsset, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    const FArrayProperty* Bodies = CastField<FArrayProperty>(PhysicsAsset->GetClass()->FindPropertyByName(TEXT("SkeletalBodySetups")));
    if (!Bodies) return true;
    const FObjectPropertyBase* InnerObject = CastField<FObjectPropertyBase>(Bodies->Inner);
    if (!InnerObject) return true;
    FScriptArrayHelper Helper(Bodies, Bodies->ContainerPtrToValuePtr<void>(PhysicsAsset));
    const TSet<FName> Excluded = { FName(TEXT("AggGeom")), FName(TEXT("CookedFormatData")) };
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        UObject* Body = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
        if (!Body) continue;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("physics_asset_path"), AssetPath);
        Row->SetNumberField(TEXT("body_index"), Index);
        Row->SetStringField(TEXT("body_path"), Body->GetPathName());
        Row->SetStringField(TEXT("body_class"), Body->GetClass()->GetPathName());
        Row->SetStringField(TEXT("bone_name"), ExportObjectProperty(Body, TEXT("BoneName")));
        Row->SetStringField(TEXT("physics_type"), ExportObjectProperty(Body, TEXT("PhysicsType")));
        Row->SetStringField(TEXT("collision_response"), ExportObjectProperty(Body, TEXT("CollisionReponse")));
        if (Row->GetStringField(TEXT("collision_response")).IsEmpty())
            Row->SetStringField(TEXT("collision_response"), ExportObjectProperty(Body, TEXT("CollisionResponse")));
        Row->SetStringField(TEXT("consider_for_bounds"), ExportObjectProperty(Body, TEXT("bConsiderForBounds")));
        Row->SetStringField(TEXT("mesh_collide_all"), ExportObjectProperty(Body, TEXT("bMeshCollideAll")));
        Row->SetStringField(TEXT("physical_animation_data"), ExportObjectProperty(Body, TEXT("PhysicalAnimationData")));
        Row->SetStringField(TEXT("physical_animation_profiles"), ExportObjectProperty(Body, TEXT("PhysicalAnimationProfiles")));
        Row->SetObjectField(TEXT("authored_properties"), ObjectFields(Body, Excluded));
        if (!Writers.PhysicsBodies.Write(Row)) return false;
        ++Counts.PhysicsBodies;
        if (!WriteBodyShapes(Body, AssetPath, Index, Writers, Counts)) return false;
    }
    return true;
}

static bool WriteConstraints(UObject* PhysicsAsset, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    const FArrayProperty* Constraints = CastField<FArrayProperty>(PhysicsAsset->GetClass()->FindPropertyByName(TEXT("ConstraintSetup")));
    if (!Constraints) return true;
    const FObjectPropertyBase* InnerObject = CastField<FObjectPropertyBase>(Constraints->Inner);
    if (!InnerObject) return true;
    FScriptArrayHelper Helper(Constraints, Constraints->ContainerPtrToValuePtr<void>(PhysicsAsset));
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        UObject* Constraint = InnerObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
        if (!Constraint) continue;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("physics_asset_path"), AssetPath);
        Row->SetNumberField(TEXT("constraint_index"), Index);
        Row->SetStringField(TEXT("constraint_path"), Constraint->GetPathName());
        Row->SetStringField(TEXT("constraint_class"), Constraint->GetClass()->GetPathName());
        Row->SetStringField(TEXT("profile_handles"), ExportObjectProperty(Constraint, TEXT("ProfileHandles")));

        const FStructProperty* DefaultInstance = CastField<FStructProperty>(Constraint->GetClass()->FindPropertyByName(TEXT("DefaultInstance")));
        if (DefaultInstance && DefaultInstance->Struct)
        {
            const void* Instance = DefaultInstance->ContainerPtrToValuePtr<void>(Constraint);
            Row->SetStringField(TEXT("joint_name"), StructFieldText(DefaultInstance->Struct, Instance, TEXT("JointName"), Constraint));
            Row->SetStringField(TEXT("constraint_bone1"), StructFieldText(DefaultInstance->Struct, Instance, TEXT("ConstraintBone1"), Constraint));
            Row->SetStringField(TEXT("constraint_bone2"), StructFieldText(DefaultInstance->Struct, Instance, TEXT("ConstraintBone2"), Constraint));
            Row->SetObjectField(TEXT("default_instance"), StructFields(DefaultInstance->Struct, Instance, Constraint));
            if (const FStructProperty* Profile = CastField<FStructProperty>(DefaultInstance->Struct->FindPropertyByName(TEXT("ProfileInstance"))))
            {
                const void* ProfileValue = Profile->ContainerPtrToValuePtr<void>(Instance);
                Row->SetObjectField(TEXT("profile_instance"), StructFields(Profile->Struct, ProfileValue, Constraint));
            }
        }
        if (!Writers.PhysicsConstraints.Write(Row)) return false;
        ++Counts.PhysicsConstraints;
    }
    return true;
}

static bool WriteCollisionDisablePairs(UObject* PhysicsAsset, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    const FMapProperty* MapProperty = CastField<FMapProperty>(PhysicsAsset->GetClass()->FindPropertyByName(TEXT("CollisionDisableTable")));
    if (!MapProperty) return true;
    FScriptMapHelper Helper(MapProperty, MapProperty->ContainerPtrToValuePtr<void>(PhysicsAsset));
    int32 PairIndex = 0;
    for (int32 SparseIndex = 0; SparseIndex < Helper.GetMaxIndex(); ++SparseIndex)
    {
        if (!Helper.IsValidIndex(SparseIndex)) continue;
        const void* Key = Helper.GetKeyPtr(SparseIndex);
        const void* Value = Helper.GetValuePtr(SparseIndex);
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("physics_asset_path"), AssetPath);
        Row->SetNumberField(TEXT("pair_index"), PairIndex++);
        Row->SetStringField(TEXT("key"), ExportProperty(MapProperty->KeyProp, Key, PhysicsAsset));
        Row->SetStringField(TEXT("value"), ExportProperty(MapProperty->ValueProp, Value, PhysicsAsset));
        if (const FStructProperty* KeyStruct = CastField<FStructProperty>(MapProperty->KeyProp))
            Row->SetObjectField(TEXT("key_fields"), StructFields(KeyStruct->Struct, Key, PhysicsAsset));
        if (!Writers.PhysicsCollisionDisablePairs.Write(Row)) return false;
        ++Counts.PhysicsCollisionDisablePairs;
    }
    return true;
}

static bool WritePhysicsAsset(UObject* PhysicsAsset, const FAssetData& Asset, FWriters& Writers, FCounts& Counts)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    auto ArrayCount = [PhysicsAsset](const TCHAR* Name) -> int32
    {
        const FArrayProperty* Array = CastField<FArrayProperty>(PhysicsAsset->GetClass()->FindPropertyByName(FName(Name)));
        if (!Array) return 0;
        FScriptArrayHelper Helper(Array, Array->ContainerPtrToValuePtr<void>(PhysicsAsset));
        return Helper.Num();
    };
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("physics_asset_path"), AssetPath);
    Row->SetStringField(TEXT("class_path"), PhysicsAsset->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetStringField(TEXT("preview_skeletal_mesh_path"), ReferencePath(PhysicsAsset, TEXT("PreviewSkeletalMesh")));
    if (Row->GetStringField(TEXT("preview_skeletal_mesh_path")).IsEmpty())
        Row->SetStringField(TEXT("preview_skeletal_mesh_path"), AssetTag(Asset, TEXT("PreviewSkeletalMesh")));
    Row->SetNumberField(TEXT("body_count"), ArrayCount(TEXT("SkeletalBodySetups")));
    Row->SetNumberField(TEXT("constraint_count"), ArrayCount(TEXT("ConstraintSetup")));
    Row->SetNumberField(TEXT("constraint_profile_count"), ArrayCount(TEXT("ConstraintProfiles")));
    Row->SetNumberField(TEXT("physical_animation_profile_count"), ArrayCount(TEXT("PhysicalAnimationProfiles")));
    if (!Writers.PhysicsAssets.Write(Row)) return false;
    ++Counts.PhysicsAssets;

    if (!WriteBodies(PhysicsAsset, AssetPath, Writers, Counts)) return false;
    if (!WriteConstraints(PhysicsAsset, AssetPath, Writers, Counts)) return false;
    if (!WriteNameArray(PhysicsAsset, TEXT("ConstraintProfiles"), AssetPath, Writers.PhysicsConstraintProfiles, Counts.PhysicsConstraintProfiles)) return false;
    if (!WriteNameArray(PhysicsAsset, TEXT("PhysicalAnimationProfiles"), AssetPath, Writers.PhysicsPhysicalAnimationProfiles, Counts.PhysicsPhysicalAnimationProfiles)) return false;
    if (!WriteCollisionDisablePairs(PhysicsAsset, AssetPath, Writers, Counts)) return false;
    return true;
}

static bool SaveManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Root->SetNumberField(TEXT("public_animation_schema_version"), PublicAnimationSchemaVersion);
    Root->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolAnimationMeshPhysics"));
    Root->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetBoolField(TEXT("runtime_state_captured"), false);
    Root->SetBoolField(TEXT("render_buffers_captured"), false);
    Root->SetBoolField(TEXT("cloth_simulation_state_captured"), false);
    Root->SetBoolField(TEXT("chaos_runtime_state_captured"), false);
    Root->SetBoolField(TEXT("maps_loaded"), false);

    TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
    C->SetNumberField(TEXT("mesh_physics_registry_candidates"), Counts.RegistryCandidates);
    C->SetNumberField(TEXT("skeletal_meshes"), Counts.SkeletalMeshes);
    C->SetNumberField(TEXT("skeletal_mesh_lods"), Counts.SkeletalMeshLods);
    C->SetNumberField(TEXT("skeletal_mesh_materials"), Counts.SkeletalMeshMaterials);
    C->SetNumberField(TEXT("skeletal_mesh_morph_targets"), Counts.SkeletalMeshMorphTargets);
    C->SetNumberField(TEXT("skeletal_mesh_clothing_assets"), Counts.SkeletalMeshClothingAssets);
    C->SetNumberField(TEXT("skeletal_mesh_clothing_configs"), Counts.SkeletalMeshClothingConfigs);
    C->SetNumberField(TEXT("physics_assets"), Counts.PhysicsAssets);
    C->SetNumberField(TEXT("physics_bodies"), Counts.PhysicsBodies);
    C->SetNumberField(TEXT("physics_body_shapes"), Counts.PhysicsBodyShapes);
    C->SetNumberField(TEXT("physics_constraints"), Counts.PhysicsConstraints);
    C->SetNumberField(TEXT("physics_constraint_profiles"), Counts.PhysicsConstraintProfiles);
    C->SetNumberField(TEXT("physics_physical_animation_profiles"), Counts.PhysicsPhysicalAnimationProfiles);
    C->SetNumberField(TEXT("physics_collision_disable_pairs"), Counts.PhysicsCollisionDisablePairs);
    Root->SetObjectField(TEXT("counts"), C);

    TArray<TSharedPtr<FJsonValue>> Files;
    static const TCHAR* Names[] = {
        TEXT("skeletal_meshes.jsonl"), TEXT("skeletal_mesh_lods.jsonl"), TEXT("skeletal_mesh_materials.jsonl"),
        TEXT("skeletal_mesh_morph_targets.jsonl"), TEXT("skeletal_mesh_clothing_assets.jsonl"), TEXT("skeletal_mesh_clothing_configs.jsonl"),
        TEXT("physics_assets.jsonl"), TEXT("physics_bodies.jsonl"), TEXT("physics_body_shapes.jsonl"), TEXT("physics_constraints.jsonl"),
        TEXT("physics_constraint_profiles.jsonl"), TEXT("physics_physical_animation_profiles.jsonl"), TEXT("physics_collision_disable_pairs.jsonl")
    };
    for (const TCHAR* Name : Names) Files.Add(MakeShared<FJsonValueString>(Name));
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    return FFileHelper::SaveStringToFile(Text, *FPaths::Combine(OutputDir, TEXT("animation_mesh_physics_manifest.json")), FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunScan(FString& OutError)
{
    FString OutputDir;
    FParse::Value(FCommandLine::Get(), TEXT("Output="), OutputDir);
    const FString ProjectDir = NormalizeAbsolutePath(FPaths::ProjectDir());
    if (OutputDir.IsEmpty()) OutputDir = FPaths::Combine(ProjectDir, TEXT(".uatool"));
    else if (FPaths::IsRelative(OutputDir)) OutputDir = FPaths::Combine(ProjectDir, OutputDir);
    OutputDir = NormalizeAbsolutePath(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    const bool bIncludeEngine = FParse::Param(FCommandLine::Get(), TEXT("IncludeEngine"));
    const bool bIncludeSelf = FParse::Param(FCommandLine::Get(), TEXT("IncludeSelf"));
    FString ToolPluginDir;
    if (const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("UnrealAssetTool")); Plugin.IsValid())
        ToolPluginDir = NormalizeAbsolutePath(Plugin->GetBaseDir());

    FWriters Writers;
    FCounts Counts;
    if (!Writers.Open(OutputDir))
    {
        OutError = TEXT("could not create animation mesh/physics JSONL output files");
        SaveManifest(OutputDir, Counts, false, OutError);
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.SearchAllAssets(true);
    TArray<FAssetData> Assets;
    Registry.GetAllAssets(Assets, true);
    Assets.Sort([](const FAssetData& A, const FAssetData& B)
    {
        return FCString::Strcmp(*A.GetSoftObjectPath().ToString(), *B.GetSoftObjectPath().ToString()) < 0;
    });

    for (const FAssetData& Asset : Assets)
    {
        const FString ClassPath = Asset.AssetClassPath.ToString();
        if (ClassPath != TEXT("/Script/Engine.SkeletalMesh") && ClassPath != TEXT("/Script/Engine.PhysicsAsset")) continue;
        FString PackageFilename;
        const bool bHasDiskPackage = FPackageName::DoesPackageExist(Asset.PackageName.ToString(), &PackageFilename, false);
        if (!bIncludeSelf && bHasDiskPackage && !ToolPluginDir.IsEmpty() && IsInsideDirectory(PackageFilename, ToolPluginDir)) continue;
        if (!bIncludeEngine && (!bHasDiskPackage || !IsInsideDirectory(PackageFilename, ProjectDir))) continue;
        ++Counts.RegistryCandidates;

        UObject* Object = Asset.GetAsset();
        if (!Object) continue;
        if (ClassPath == TEXT("/Script/Engine.SkeletalMesh"))
        {
            if (!WriteSkeletalMesh(Object, Asset, Writers, Counts))
            {
                OutError = TEXT("failed while scanning SkeletalMesh ") + Asset.GetSoftObjectPath().ToString();
                Writers.Close();
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
        }
        else
        {
            if (!WritePhysicsAsset(Object, Asset, Writers, Counts))
            {
                OutError = TEXT("failed while scanning PhysicsAsset ") + Asset.GetSoftObjectPath().ToString();
                Writers.Close();
                SaveManifest(OutputDir, Counts, false, OutError);
                return false;
            }
        }
    }

    if (!Writers.Close())
    {
        OutError = TEXT("failed closing animation mesh/physics output streams");
        SaveManifest(OutputDir, Counts, false, OutError);
        return false;
    }
    if (!SaveManifest(OutputDir, Counts, true, FString()))
    {
        OutError = TEXT("could not write animation_mesh_physics_manifest.json");
        return false;
    }
    UE_LOG(LogTemp, Display,
        TEXT("UnrealAssetToolAnimationMeshPhysics: meshes=%lld lods=%lld materials=%lld morphs=%lld clothing=%lld physics_assets=%lld bodies=%lld shapes=%lld constraints=%lld"),
        Counts.SkeletalMeshes, Counts.SkeletalMeshLods, Counts.SkeletalMeshMaterials, Counts.SkeletalMeshMorphTargets,
        Counts.SkeletalMeshClothingAssets, Counts.PhysicsAssets, Counts.PhysicsBodies, Counts.PhysicsBodyShapes, Counts.PhysicsConstraints);
    return true;
}

static void OnPostEngineInit()
{
    FString RunCommandlet;
    FParse::Value(FCommandLine::Get(), TEXT("run="), RunCommandlet);
    if (!RunCommandlet.Equals(TEXT("UnrealAssetToolWorld"), ESearchCase::IgnoreCase)) return;
    FString Error;
    if (!RunScan(Error)) UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolAnimationMeshPhysics: %s"), *Error);
}

struct FBootstrap
{
    FBootstrap() { FCoreDelegates::GetOnPostEngineInit().AddStatic(&OnPostEngineInit); }
};

static FBootstrap GBootstrap;
} // namespace UnrealAssetToolAnimationMeshPhysics
