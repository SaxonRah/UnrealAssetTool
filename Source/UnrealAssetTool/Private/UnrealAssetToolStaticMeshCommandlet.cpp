#include "UnrealAssetToolStaticMeshCommandlet.h"

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

namespace UnrealAssetToolStaticMesh
{
constexpr int32 SchemaVersion = 2;
constexpr int32 MaxExportChars = 32768;
static const TCHAR* StaticMeshClassPath = TEXT("/Script/Engine.StaticMesh");

static const TCHAR* RegistryTagNames[] = {
    TEXT("LODs"), TEXT("LODGroup"), TEXT("MinLOD"), TEXT("QualityLevelMinLOD"),
    TEXT("Materials"), TEXT("StaticMaterials"), TEXT("SectionsWithCollision"),
    TEXT("CollisionComplexity"), TEXT("CollisionPrims"), TEXT("DefaultCollision"),
    TEXT("NaniteEnabled"), TEXT("NaniteFallbackPercent"), TEXT("NaniteTriangles"),
    TEXT("NaniteVertices"), TEXT("EstNaniteCompressedSize"), TEXT("HasHiResMesh"),
    TEXT("Triangles"), TEXT("Vertices"), TEXT("UVChannels"), TEXT("DistanceFieldSize"),
    TEXT("NeverStream")
};

static const TCHAR* SelectedMeshProperties[] = {
    TEXT("NaniteSettings"), TEXT("SectionInfoMap"), TEXT("OriginalSectionInfoMap"),
    TEXT("LightMapCoordinateIndex"), TEXT("LightMapResolution"), TEXT("MinLOD"),
    TEXT("LODGroup"), TEXT("bAllowCPUAccess"), TEXT("bSupportRayTracing"),
    TEXT("bSupportPhysicalMaterialMasks"), TEXT("bGenerateMeshDistanceField"),
    TEXT("DistanceFieldSelfShadowBias"), TEXT("ComplexCollisionMesh"),
    TEXT("bAutoComputeLODScreenSize"), TEXT("bSupportUniformlyDistributedSampling"),
    TEXT("bSupportGpuUniformlyDistributedSampling"), TEXT("PositiveBoundsExtension"),
    TEXT("NegativeBoundsExtension")
};

struct FCounts
{
    int64 RegistryCandidates = 0;
    int64 StaticMeshes = 0;
    int64 LoadFailures = 0;
    int64 SourceModels = 0;
    int64 Materials = 0;
    int64 Sockets = 0;
    int64 BodySetups = 0;
    int64 CollisionShapes = 0;
    int64 SelectedProperties = 0;
    int64 RegistryMultiLodAssets = 0;
    int64 RegistryNaniteEnabledAssets = 0;
    int64 RegistryCollisionPrimitiveAssets = 0;
    int64 RegistryMaterialAssets = 0;
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
    FJsonlWriter Assets;
    FJsonlWriter SourceModels;
    FJsonlWriter Materials;
    FJsonlWriter Sockets;
    FJsonlWriter BodySetups;
    FJsonlWriter CollisionShapes;
    FJsonlWriter Properties;

    bool Open(const FString& OutputDir)
    {
        return Assets.Open(FPaths::Combine(OutputDir, TEXT("staticmesh_assets.jsonl"))) &&
            SourceModels.Open(FPaths::Combine(OutputDir, TEXT("staticmesh_source_models.jsonl"))) &&
            Materials.Open(FPaths::Combine(OutputDir, TEXT("staticmesh_materials.jsonl"))) &&
            Sockets.Open(FPaths::Combine(OutputDir, TEXT("staticmesh_sockets.jsonl"))) &&
            BodySetups.Open(FPaths::Combine(OutputDir, TEXT("staticmesh_body_setups.jsonl"))) &&
            CollisionShapes.Open(FPaths::Combine(OutputDir, TEXT("staticmesh_collision_shapes.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("staticmesh_properties.jsonl")));
    }

    bool Close()
    {
        bool bOk = true;
        bOk = Assets.Close() && bOk;
        bOk = SourceModels.Close() && bOk;
        bOk = Materials.Close() && bOk;
        bOk = Sockets.Close() && bOk;
        bOk = BodySetups.Close() && bOk;
        bOk = CollisionShapes.Close() && bOk;
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

static bool ParseBoolTag(const FAssetData& Asset, const TCHAR* Name)
{
    const FString Value = AssetTag(Asset, Name);
    return Value.Equals(TEXT("True"), ESearchCase::IgnoreCase) || Value == TEXT("1");
}

static TSharedRef<FJsonObject> RegistryTags(const FAssetData& Asset)
{
    TSharedRef<FJsonObject> Tags = MakeShared<FJsonObject>();
    for (const TCHAR* Name : RegistryTagNames)
    {
        FString Value;
        if (Asset.GetTagValue(FName(Name), Value)) Tags->SetStringField(Name, Value);
    }
    return Tags;
}

static TSharedRef<FJsonObject> StructFields(
    const UStruct* Struct,
    const void* ValuePtr,
    UObject* Owner,
    const TSet<FName>& Excluded = {})
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

static bool IsSafeSelectedStructLeaf(const FProperty* Field)
{
    if (!Field) return false;
    return
        CastField<FBoolProperty>(Field) != nullptr ||
        CastField<FNumericProperty>(Field) != nullptr ||
        CastField<FEnumProperty>(Field) != nullptr ||
        CastField<FNameProperty>(Field) != nullptr ||
        CastField<FStrProperty>(Field) != nullptr ||
        CastField<FTextProperty>(Field) != nullptr;
}

static TSharedRef<FJsonObject> SelectedStructFields(
    const UStruct* Struct,
    const void* ValuePtr,
    UObject* Owner)
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    if (!Struct || !ValuePtr) return Result;

    // Selected StaticMesh structs can contain editor-only object/container
    // internals that are unsafe to feed through generic ExportTextItem_Direct.
    // Preserve only direct scalar leaves here. The complete top-level selected
    // property text is still captured separately by WriteSelectedProperties.
    for (TFieldIterator<FProperty> It(Struct); It; ++It)
    {
        const FProperty* Field = *It;
        if (!ShouldInspectProperty(Field) || !IsSafeSelectedStructLeaf(Field)) continue;

        for (int32 StaticIndex = 0; StaticIndex < Field->ArrayDim; ++StaticIndex)
        {
            FString Key = Field->GetName();
            if (Field->ArrayDim > 1) Key += FString::Printf(TEXT("[%d]"), StaticIndex);

            const void* FieldValue = Field->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
            if (!FieldValue) continue;
            Result->SetStringField(Key, ExportProperty(Field, FieldValue, Owner));
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
    return Field ? Field->GetObjectPropertyValue(Field->ContainerPtrToValuePtr<void>(ValuePtr)) : nullptr;
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

static bool WriteSelectedProperties(UObject* Mesh, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    UE_LOG(LogTemp, Display, TEXT("UnrealAssetToolStaticMesh selected properties: %s"), *AssetPath);
    for (const TCHAR* Name : SelectedMeshProperties)
    {
        const FProperty* Property = Mesh->GetClass()->FindPropertyByName(FName(Name));
        if (!Property || !ShouldInspectProperty(Property)) continue;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("static_mesh_path"), AssetPath);
        Row->SetStringField(TEXT("property_name"), Property->GetName());
        Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
        Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
        Row->SetStringField(TEXT("value"), ExportProperty(Property, Property->ContainerPtrToValuePtr<void>(Mesh), Mesh));
        if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
        {
            Row->SetStringField(TEXT("struct_type"), StructProperty->Struct ? StructProperty->Struct->GetPathName() : FString());
            if (StructProperty->Struct)
                Row->SetObjectField(
                    TEXT("fields"),
                    SelectedStructFields(
                        StructProperty->Struct,
                        Property->ContainerPtrToValuePtr<void>(Mesh),
                        Mesh));
        }
        if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
        {
            UObject* Target = ObjectProperty->GetObjectPropertyValue(Property->ContainerPtrToValuePtr<void>(Mesh));
            Row->SetStringField(TEXT("target_path"), Target ? Target->GetPathName() : FString());
            Row->SetStringField(TEXT("target_class"), Target ? Target->GetClass()->GetPathName() : FString());
        }
        if (!Writers.Properties.Write(Row)) return false;
        ++Counts.SelectedProperties;
    }
    return true;
}

static bool WriteSourceModels(UObject* Mesh, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    const FArrayProperty* SourceModels = CastField<FArrayProperty>(Mesh->GetClass()->FindPropertyByName(TEXT("SourceModels")));
    if (!SourceModels) return true;
    const FStructProperty* SourceStruct = CastField<FStructProperty>(SourceModels->Inner);
    if (!SourceStruct || !SourceStruct->Struct) return true;
    FScriptArrayHelper Helper(SourceModels, SourceModels->ContainerPtrToValuePtr<void>(Mesh));
    const TSet<FName> Excluded = {
        FName(TEXT("RawMeshBulkData")), FName(TEXT("MeshDescriptionBulkData")),
        FName(TEXT("HiResSourceModel")), FName(TEXT("BuildSettings")), FName(TEXT("ReductionSettings"))
    };
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Value = Helper.GetRawPtr(Index);
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("static_mesh_path"), AssetPath);
        Row->SetNumberField(TEXT("lod_index"), Index);
        Row->SetStringField(TEXT("source_model_struct"), SourceStruct->Struct->GetPathName());
        Row->SetObjectField(TEXT("fields"), StructFields(SourceStruct->Struct, Value, Mesh, Excluded));
        if (const FStructProperty* Build = CastField<FStructProperty>(SourceStruct->Struct->FindPropertyByName(TEXT("BuildSettings"))))
        {
            Row->SetStringField(TEXT("build_settings_struct"), Build->Struct ? Build->Struct->GetPathName() : FString());
            if (Build->Struct)
                Row->SetObjectField(TEXT("build_settings"), StructFields(Build->Struct, Build->ContainerPtrToValuePtr<void>(Value), Mesh));
        }
        if (const FStructProperty* Reduction = CastField<FStructProperty>(SourceStruct->Struct->FindPropertyByName(TEXT("ReductionSettings"))))
        {
            Row->SetStringField(TEXT("reduction_settings_struct"), Reduction->Struct ? Reduction->Struct->GetPathName() : FString());
            if (Reduction->Struct)
                Row->SetObjectField(TEXT("reduction_settings"), StructFields(Reduction->Struct, Reduction->ContainerPtrToValuePtr<void>(Value), Mesh));
        }
        if (!Writers.SourceModels.Write(Row)) return false;
        ++Counts.SourceModels;
    }
    return true;
}

static bool WriteMaterials(UObject* Mesh, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    const FArrayProperty* Materials = CastField<FArrayProperty>(Mesh->GetClass()->FindPropertyByName(TEXT("StaticMaterials")));
    if (!Materials) return true;
    const FStructProperty* MaterialStruct = CastField<FStructProperty>(Materials->Inner);
    if (!MaterialStruct || !MaterialStruct->Struct) return true;
    FScriptArrayHelper Helper(Materials, Materials->ContainerPtrToValuePtr<void>(Mesh));
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        const void* Value = Helper.GetRawPtr(Index);
        UObject* Material = StructObjectField(MaterialStruct->Struct, Value, TEXT("MaterialInterface"));
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("static_mesh_path"), AssetPath);
        Row->SetNumberField(TEXT("material_index"), Index);
        Row->SetStringField(TEXT("material_path"), Material ? Material->GetPathName() : FString());
        Row->SetStringField(TEXT("material_class"), Material ? Material->GetClass()->GetPathName() : FString());
        Row->SetStringField(TEXT("material_slot_name"), StructFieldText(MaterialStruct->Struct, Value, TEXT("MaterialSlotName"), Mesh));
        Row->SetStringField(TEXT("imported_material_slot_name"), StructFieldText(MaterialStruct->Struct, Value, TEXT("ImportedMaterialSlotName"), Mesh));
        Row->SetStringField(TEXT("uv_channel_data"), StructFieldText(MaterialStruct->Struct, Value, TEXT("UVChannelData"), Mesh));
        if (!Writers.Materials.Write(Row)) return false;
        ++Counts.Materials;
    }
    return true;
}

static bool WriteSockets(UObject* Mesh, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    const FArrayProperty* Sockets = CastField<FArrayProperty>(Mesh->GetClass()->FindPropertyByName(TEXT("Sockets")));
    if (!Sockets) return true;
    const FObjectPropertyBase* SocketObject = CastField<FObjectPropertyBase>(Sockets->Inner);
    if (!SocketObject) return true;
    FScriptArrayHelper Helper(Sockets, Sockets->ContainerPtrToValuePtr<void>(Mesh));
    for (int32 Index = 0; Index < Helper.Num(); ++Index)
    {
        UObject* Socket = SocketObject->GetObjectPropertyValue(Helper.GetRawPtr(Index));
        if (!Socket) continue;
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("static_mesh_path"), AssetPath);
        Row->SetNumberField(TEXT("socket_index"), Index);
        Row->SetStringField(TEXT("socket_path"), Socket->GetPathName());
        Row->SetStringField(TEXT("socket_class"), Socket->GetClass()->GetPathName());
        Row->SetStringField(TEXT("socket_name"), ObjectFieldText(Socket, TEXT("SocketName")));
        Row->SetStringField(TEXT("relative_location"), ObjectFieldText(Socket, TEXT("RelativeLocation")));
        Row->SetStringField(TEXT("relative_rotation"), ObjectFieldText(Socket, TEXT("RelativeRotation")));
        Row->SetStringField(TEXT("relative_scale"), ObjectFieldText(Socket, TEXT("RelativeScale")));
        Row->SetStringField(TEXT("tag"), ObjectFieldText(Socket, TEXT("Tag")));
        if (!Writers.Sockets.Write(Row)) return false;
        ++Counts.Sockets;
    }
    return true;
}

static bool WriteCollisionShapes(UObject* BodySetup, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    if (!BodySetup) return true;
    const FStructProperty* AggGeom = CastField<FStructProperty>(BodySetup->GetClass()->FindPropertyByName(TEXT("AggGeom")));
    if (!AggGeom || !AggGeom->Struct) return true;
    const void* AggValue = AggGeom->ContainerPtrToValuePtr<void>(BodySetup);
    static const TCHAR* ShapeArrays[] = {
        TEXT("SphereElems"), TEXT("BoxElems"), TEXT("SphylElems"), TEXT("ConvexElems"),
        TEXT("TaperedCapsuleElems"), TEXT("LevelSetElems"), TEXT("SkinnedLevelSetElems")
    };
    for (const TCHAR* ShapeArrayName : ShapeArrays)
    {
        const FArrayProperty* Shapes = CastField<FArrayProperty>(AggGeom->Struct->FindPropertyByName(FName(ShapeArrayName)));
        if (!Shapes) continue;
        const FStructProperty* ShapeStruct = CastField<FStructProperty>(Shapes->Inner);
        FScriptArrayHelper Helper(Shapes, Shapes->ContainerPtrToValuePtr<void>(const_cast<void*>(AggValue)));
        for (int32 ShapeIndex = 0; ShapeIndex < Helper.Num(); ++ShapeIndex)
        {
            const void* ShapeValue = Helper.GetRawPtr(ShapeIndex);
            TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
            Row->SetStringField(TEXT("static_mesh_path"), AssetPath);
            Row->SetStringField(TEXT("body_setup_path"), BodySetup->GetPathName());
            Row->SetStringField(TEXT("shape_type"), ShapeArrayName);
            Row->SetNumberField(TEXT("shape_index"), ShapeIndex);
            Row->SetStringField(TEXT("shape_struct"), ShapeStruct && ShapeStruct->Struct ? ShapeStruct->Struct->GetPathName() : FString());
            if (ShapeStruct && ShapeStruct->Struct)
                Row->SetObjectField(TEXT("fields"), StructFields(ShapeStruct->Struct, ShapeValue, BodySetup));
            Row->SetStringField(TEXT("raw_value"), ExportProperty(Shapes->Inner, ShapeValue, BodySetup));
            if (!Writers.CollisionShapes.Write(Row)) return false;
            ++Counts.CollisionShapes;
        }
    }
    return true;
}

static bool WriteBodySetup(UObject* Mesh, const FString& AssetPath, FWriters& Writers, FCounts& Counts)
{
    UObject* BodySetup = ObjectField(Mesh, TEXT("BodySetup"));
    if (!BodySetup) return true;
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("static_mesh_path"), AssetPath);
    Row->SetStringField(TEXT("body_setup_path"), BodySetup->GetPathName());
    Row->SetStringField(TEXT("body_setup_class"), BodySetup->GetClass()->GetPathName());
    Row->SetStringField(TEXT("collision_trace_flag"), ObjectFieldText(BodySetup, TEXT("CollisionTraceFlag")));
    Row->SetStringField(TEXT("default_instance"), ObjectFieldText(BodySetup, TEXT("DefaultInstance")));
    Row->SetStringField(TEXT("phys_material"), ObjectFieldText(BodySetup, TEXT("PhysMaterial")));
    Row->SetStringField(TEXT("build_scale3d"), ObjectFieldText(BodySetup, TEXT("BuildScale3D")));
    Row->SetStringField(TEXT("walkable_slope_override"), ObjectFieldText(BodySetup, TEXT("WalkableSlopeOverride")));
    Row->SetStringField(TEXT("double_sided_geometry"), ObjectFieldText(BodySetup, TEXT("bDoubleSidedGeometry")));
    Row->SetStringField(TEXT("never_needs_cooked_collision_data"), ObjectFieldText(BodySetup, TEXT("bNeverNeedsCookedCollisionData")));
    if (!Writers.BodySetups.Write(Row)) return false;
    ++Counts.BodySetups;
    return WriteCollisionShapes(BodySetup, AssetPath, Writers, Counts);
}

static bool WriteMesh(const FAssetData& Asset, UObject* Mesh, FWriters& Writers, FCounts& Counts)
{
    const FString AssetPath = Asset.GetSoftObjectPath().ToString();
    const int32 RegistryLods = ParseIntTag(Asset, TEXT("LODs"));
    const int32 RegistryMaterials = ParseIntTag(Asset, TEXT("Materials"));
    const int32 RegistryCollisionPrims = ParseIntTag(Asset, TEXT("CollisionPrims"));
    const bool bRegistryNanite = ParseBoolTag(Asset, TEXT("NaniteEnabled"));

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("static_mesh_path"), AssetPath);
    Row->SetStringField(TEXT("class_path"), Mesh->GetClass()->GetPathName());
    Row->SetStringField(TEXT("package_name"), Asset.PackageName.ToString());
    Row->SetObjectField(TEXT("registry_tags"), RegistryTags(Asset));
    Row->SetNumberField(TEXT("registry_lod_count"), RegistryLods);
    Row->SetNumberField(TEXT("registry_material_count"), RegistryMaterials);
    Row->SetNumberField(TEXT("registry_collision_prim_count"), RegistryCollisionPrims);
    Row->SetBoolField(TEXT("registry_nanite_enabled"), bRegistryNanite);
    Row->SetNumberField(TEXT("source_model_count"), ArrayCount(Mesh, TEXT("SourceModels")));
    Row->SetNumberField(TEXT("static_material_count"), ArrayCount(Mesh, TEXT("StaticMaterials")));
    Row->SetNumberField(TEXT("socket_count"), ArrayCount(Mesh, TEXT("Sockets")));
    UObject* BodySetup = ObjectField(Mesh, TEXT("BodySetup"));
    Row->SetStringField(TEXT("body_setup_path"), BodySetup ? BodySetup->GetPathName() : FString());
    Row->SetStringField(TEXT("complex_collision_mesh_path"), ObjectField(Mesh, TEXT("ComplexCollisionMesh")) ? ObjectField(Mesh, TEXT("ComplexCollisionMesh"))->GetPathName() : FString());
    if (!Writers.Assets.Write(Row)) return false;
    ++Counts.StaticMeshes;
    if (RegistryLods > 1) ++Counts.RegistryMultiLodAssets;
    if (bRegistryNanite) ++Counts.RegistryNaniteEnabledAssets;
    if (RegistryCollisionPrims > 0) ++Counts.RegistryCollisionPrimitiveAssets;
    if (RegistryMaterials > 0) ++Counts.RegistryMaterialAssets;

    return WriteSourceModels(Mesh, AssetPath, Writers, Counts) &&
        WriteMaterials(Mesh, AssetPath, Writers, Counts) &&
        WriteSockets(Mesh, AssetPath, Writers, Counts) &&
        WriteBodySetup(Mesh, AssetPath, Writers, Counts) &&
        WriteSelectedProperties(Mesh, AssetPath, Writers, Counts);
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
    Root->SetBoolField(TEXT("render_buffers_captured"), false);
    Root->SetBoolField(TEXT("nanite_resources_captured"), false);
    Root->SetBoolField(TEXT("runtime_physics_state_captured"), false);
    Root->SetBoolField(TEXT("maps_loaded"), false);
    Root->SetBoolField(TEXT("include_engine"), bIncludeEngine);
    Root->SetStringField(
        TEXT("selected_struct_field_policy"),
        TEXT("direct_safe_scalar_leaves_only: bool,numeric,enum,name,string,text; object/container/delegate/nested-struct members skipped"));
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("capture_scope"), TEXT("exact project StaticMesh authored source models/build-reduction settings, static material slots, sockets, BodySetup/simple collision shapes, selected Nanite/section/lightmap/collision properties; no render buffers, generated Nanite resources, cooked collision or runtime physics"));

    TSharedRef<FJsonObject> C = MakeShared<FJsonObject>();
    C->SetNumberField(TEXT("registry_candidates"), Counts.RegistryCandidates);
    C->SetNumberField(TEXT("static_meshes"), Counts.StaticMeshes);
    C->SetNumberField(TEXT("load_failures"), Counts.LoadFailures);
    C->SetNumberField(TEXT("source_models"), Counts.SourceModels);
    C->SetNumberField(TEXT("materials"), Counts.Materials);
    C->SetNumberField(TEXT("sockets"), Counts.Sockets);
    C->SetNumberField(TEXT("body_setups"), Counts.BodySetups);
    C->SetNumberField(TEXT("collision_shapes"), Counts.CollisionShapes);
    C->SetNumberField(TEXT("selected_properties"), Counts.SelectedProperties);
    C->SetNumberField(TEXT("registry_multi_lod_assets"), Counts.RegistryMultiLodAssets);
    C->SetNumberField(TEXT("registry_nanite_enabled_assets"), Counts.RegistryNaniteEnabledAssets);
    C->SetNumberField(TEXT("registry_collision_primitive_assets"), Counts.RegistryCollisionPrimitiveAssets);
    C->SetNumberField(TEXT("registry_material_assets"), Counts.RegistryMaterialAssets);
    Root->SetObjectField(TEXT("counts"), C);

    TArray<TSharedPtr<FJsonValue>> Files;
    static const TCHAR* Names[] = {
        TEXT("staticmesh_assets.jsonl"), TEXT("staticmesh_source_models.jsonl"),
        TEXT("staticmesh_materials.jsonl"), TEXT("staticmesh_sockets.jsonl"),
        TEXT("staticmesh_body_setups.jsonl"), TEXT("staticmesh_collision_shapes.jsonl"),
        TEXT("staticmesh_properties.jsonl")
    };
    for (const TCHAR* Name : Names) Files.Add(MakeShared<FJsonValueString>(Name));
    Root->SetArrayField(TEXT("files"), Files);

    FString Text;
    const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("staticmesh_capture_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

static bool RunCapture(const FString& OutputDir, bool bIncludeEngine, FCounts& Counts, FString& OutError)
{
    FWriters Writers;
    if (!Writers.Open(OutputDir))
    {
        OutError = TEXT("could not open StaticMesh capture writers");
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
        if (!Asset.AssetClassPath.ToString().Equals(StaticMeshClassPath, ESearchCase::CaseSensitive)) continue;
        if (!AssetInScope(Asset, ProjectDir, bIncludeEngine)) continue;
        ++Counts.RegistryCandidates;

        UObject* Mesh = Asset.GetAsset();
        if (!Mesh)
        {
            ++Counts.LoadFailures;
            continue;
        }
        if (!Mesh->GetClass()->GetPathName().Equals(StaticMeshClassPath, ESearchCase::CaseSensitive))
        {
            OutError = TEXT("loaded class mismatch for ") + Asset.GetSoftObjectPath().ToString();
            Writers.Close();
            return false;
        }
        if (!WriteMesh(Asset, Mesh, Writers, Counts))
        {
            OutError = TEXT("failed writing StaticMesh ") + Asset.GetSoftObjectPath().ToString();
            Writers.Close();
            return false;
        }
    }

    if (!Writers.Close())
    {
        OutError = TEXT("failed closing StaticMesh capture writers");
        return false;
    }
    return true;
}
} // namespace UnrealAssetToolStaticMesh

UUnrealAssetToolStaticMeshCommandlet::UUnrealAssetToolStaticMeshCommandlet()
{
    IsClient = false;
    IsEditor = true;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolStaticMeshCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolStaticMesh;

    FString OutputDir;
    FParse::Value(*Params, TEXT("Output="), OutputDir);
    if (OutputDir.IsEmpty())
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), TEXT(".uatool"), TEXT("staticmesh-native-capture"));
    else if (FPaths::IsRelative(OutputDir))
        OutputDir = FPaths::Combine(FPaths::ProjectDir(), OutputDir);
    OutputDir = NormalizeAbsolutePath(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    const bool bIncludeEngine = FParse::Param(*Params, TEXT("IncludeEngine"));
    FCounts Counts;
    FString Error;
    const bool bSuccess = RunCapture(OutputDir, bIncludeEngine, Counts, Error);
    if (!WriteManifest(OutputDir, Counts, bSuccess, Error, bIncludeEngine))
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolStaticMesh: failed writing capture manifest"));
        return 2;
    }
    if (!bSuccess)
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolStaticMesh: %s"), *Error);
        return 1;
    }

    UE_LOG(LogTemp, Display,
        TEXT("UnrealAssetToolStaticMesh captured %lld meshes, %lld source models, %lld materials, %lld sockets, %lld body setups, %lld collision shapes"),
        Counts.StaticMeshes, Counts.SourceModels, Counts.Materials, Counts.Sockets,
        Counts.BodySetups, Counts.CollisionShapes);
    return Counts.LoadFailures == 0 ? 0 : 3;
}
