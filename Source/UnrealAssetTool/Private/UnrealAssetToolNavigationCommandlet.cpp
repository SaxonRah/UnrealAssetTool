#include "UnrealAssetToolNavigationCommandlet.h"

#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/SoftObjectPtr.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UObjectHash.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolNavigation
{
constexpr int32 SchemaVersion = 1;
constexpr int32 MaxExportChars = 65536;
constexpr int32 MaxDepth = 8;
constexpr int32 MaxContainerElements = 512;

struct FCounts
{
    int64 Classes = 0;
    int64 AreaClasses = 0;
    int64 CDOProperties = 0;
    int64 CDOReferences = 0;
    int64 ConfigProperties = 0;
    int64 TruncatedValues = 0;
    int64 DepthLimitHits = 0;
    int64 ContainerLimitHits = 0;
    int64 MissingExpectedClasses = 0;
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
    FJsonlWriter Classes;
    FJsonlWriter Properties;
    FJsonlWriter References;

    bool Open(const FString& OutputDir)
    {
        return Classes.Open(FPaths::Combine(OutputDir, TEXT("navigation_classes.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("navigation_cdo_properties.jsonl"))) &&
            References.Open(FPaths::Combine(OutputDir, TEXT("navigation_cdo_references.jsonl")));
    }

    bool Close()
    {
        bool bOk = true;
        bOk = Classes.Close() && bOk;
        bOk = Properties.Close() && bOk;
        bOk = References.Close() && bOk;
        return bOk;
    }
};

static const TCHAR* ExpectedClassPaths[] = {
    TEXT("/Script/NavigationSystem.NavArea"),
    TEXT("/Script/NavigationSystem.NavArea_Default"),
    TEXT("/Script/NavigationSystem.NavArea_Null"),
    TEXT("/Script/NavigationSystem.NavArea_Obstacle"),
    TEXT("/Script/NavigationSystem.NavigationSystemV1"),
    TEXT("/Script/Engine.NavigationSystemConfig"),
    TEXT("/Script/NavigationSystem.NavigationInvokerComponent"),
    TEXT("/Script/NavigationSystem.NavModifierComponent"),
    TEXT("/Script/NavigationSystem.NavModifierVolume"),
    TEXT("/Script/AIModule.NavLinkProxy"),
    TEXT("/Script/NavigationSystem.NavLinkCustomComponent"),
    TEXT("/Script/NavigationSystem.NavMeshBoundsVolume"),
    TEXT("/Script/NavigationSystem.RecastNavMesh"),
};

static FString ClassKind(const UClass* Class, const UClass* NavAreaBase)
{
    if (!Class) return TEXT("unknown");
    const FString Path = Class->GetPathName();
    if (NavAreaBase && Class->IsChildOf(NavAreaBase)) return TEXT("nav_area");
    if (Path == TEXT("/Script/NavigationSystem.NavigationSystemV1")) return TEXT("navigation_system");
    if (Path == TEXT("/Script/Engine.NavigationSystemConfig")) return TEXT("navigation_system_config");
    if (Path == TEXT("/Script/NavigationSystem.NavigationInvokerComponent")) return TEXT("navigation_invoker_component");
    if (Path == TEXT("/Script/NavigationSystem.NavModifierComponent")) return TEXT("nav_modifier_component");
    if (Path == TEXT("/Script/NavigationSystem.NavModifierVolume")) return TEXT("nav_modifier_volume");
    if (Path == TEXT("/Script/AIModule.NavLinkProxy")) return TEXT("nav_link_proxy");
    if (Path == TEXT("/Script/NavigationSystem.NavLinkCustomComponent")) return TEXT("nav_link_custom_component");
    if (Path == TEXT("/Script/NavigationSystem.NavMeshBoundsVolume")) return TEXT("navmesh_bounds_volume");
    if (Path == TEXT("/Script/NavigationSystem.RecastNavMesh")) return TEXT("recast_navmesh_defaults");
    return TEXT("navigation_class");
}

static bool ShouldInspectProperty(const FProperty* Property)
{
    if (!Property) return false;
    constexpr EPropertyFlags Rejected =
        CPF_Transient | CPF_DuplicateTransient | CPF_NonPIEDuplicateTransient |
        CPF_Deprecated | CPF_SkipSerialization;
    return !Property->HasAnyPropertyFlags(Rejected);
}

static FString ExportProperty(const FProperty* Property, const void* ValuePtr, UObject* Owner, bool& bTruncated)
{
    bTruncated = false;
    if (!Property || !ValuePtr) return FString();
    FString Text;
    Property->ExportTextItem_Direct(Text, ValuePtr, nullptr, Owner, PPF_None, nullptr);
    if (Text.Len() > MaxExportChars)
    {
        Text.LeftInline(MaxExportChars, EAllowShrinking::No);
        bTruncated = true;
    }
    return Text;
}

static bool WriteReference(
    const FProperty* Property,
    const void* ValuePtr,
    const FString& ClassPath,
    const FString& PropertyPath,
    FJsonlWriter& Writer,
    FCounts& Counts)
{
    FString TargetPath;
    FString TargetClass;
    FString Kind;

    if (const FSoftObjectProperty* SoftProperty = CastField<FSoftObjectProperty>(Property))
    {
        const FSoftObjectPtr* Ptr = static_cast<const FSoftObjectPtr*>(ValuePtr);
        if (Ptr && !Ptr->IsNull())
        {
            TargetPath = Ptr->ToSoftObjectPath().ToString();
            Kind = TEXT("soft_object");
        }
    }
    else if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        if (UObject* Target = ObjectProperty->GetObjectPropertyValue(ValuePtr))
        {
            TargetPath = Target->GetPathName();
            TargetClass = Target->GetClass()->GetPathName();
            Kind = TEXT("hard_object");
        }
    }

    if (TargetPath.IsEmpty()) return true;

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("class_path"), ClassPath);
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("reference_kind"), Kind);
    Row->SetStringField(TEXT("target_path"), TargetPath);
    Row->SetStringField(TEXT("target_class"), TargetClass);
    if (!Writer.Write(Row)) return false;
    ++Counts.CDOReferences;
    return true;
}

static bool WritePropertyRecursive(
    const FProperty* Property,
    const void* ValuePtr,
    UObject* CDO,
    const FString& ClassPath,
    const FString& RootProperty,
    const FString& PropertyPath,
    int32 Depth,
    FJsonlWriter& PropertyWriter,
    FJsonlWriter& ReferenceWriter,
    FCounts& Counts)
{
    if (!Property || !ValuePtr || !ShouldInspectProperty(Property)) return true;

    bool bTruncated = false;
    const FString Value = ExportProperty(Property, ValuePtr, CDO, bTruncated);
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("class_path"), ClassPath);
    Row->SetStringField(TEXT("cdo_path"), CDO ? CDO->GetPathName() : FString());
    Row->SetNumberField(TEXT("depth"), Depth);
    Row->SetStringField(TEXT("declaring_type"), Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : FString());
    Row->SetStringField(TEXT("root_property"), RootProperty);
    Row->SetStringField(TEXT("property_name"), Property->GetName());
    Row->SetStringField(TEXT("property_path"), PropertyPath);
    Row->SetStringField(TEXT("property_type"), Property->GetClass()->GetName());
    Row->SetStringField(TEXT("cpp_type"), Property->GetCPPType());
    Row->SetStringField(TEXT("value"), Value);
    Row->SetNumberField(TEXT("property_flags"), static_cast<double>(Property->GetPropertyFlags()));
    Row->SetBoolField(TEXT("config_property"), Property->HasAnyPropertyFlags(CPF_Config));
    Row->SetBoolField(TEXT("edit_property"), Property->HasAnyPropertyFlags(CPF_Edit));
    Row->SetBoolField(TEXT("truncated"), bTruncated);
    if (!PropertyWriter.Write(Row)) return false;
    ++Counts.CDOProperties;
    if (Property->HasAnyPropertyFlags(CPF_Config)) ++Counts.ConfigProperties;
    if (bTruncated) ++Counts.TruncatedValues;

    if (!WriteReference(Property, ValuePtr, ClassPath, PropertyPath, ReferenceWriter, Counts))
        return false;

    if (Depth >= MaxDepth)
    {
        if (CastField<FStructProperty>(Property) || CastField<FArrayProperty>(Property))
            ++Counts.DepthLimitHits;
        return true;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        for (TFieldIterator<FProperty> It(StructProperty->Struct); It; ++It)
        {
            const FProperty* Child = *It;
            if (!ShouldInspectProperty(Child)) continue;
            for (int32 StaticIndex = 0; StaticIndex < Child->ArrayDim; ++StaticIndex)
            {
                const void* ChildPtr = Child->ContainerPtrToValuePtr<void>(ValuePtr, StaticIndex);
                FString ChildPath = PropertyPath + TEXT(".") + Child->GetName();
                if (Child->ArrayDim > 1)
                    ChildPath += FString::Printf(TEXT("[%d]"), StaticIndex);
                if (!WritePropertyRecursive(
                        Child, ChildPtr, CDO, ClassPath, RootProperty, ChildPath,
                        Depth + 1, PropertyWriter, ReferenceWriter, Counts))
                    return false;
            }
        }
    }
    else if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        FScriptArrayHelper Helper(ArrayProperty, const_cast<void*>(ValuePtr));
        const int32 Limit = FMath::Min(Helper.Num(), MaxContainerElements);
        if (Helper.Num() > Limit) ++Counts.ContainerLimitHits;
        for (int32 Index = 0; Index < Limit; ++Index)
        {
            if (!WritePropertyRecursive(
                    ArrayProperty->Inner, Helper.GetRawPtr(Index), CDO, ClassPath, RootProperty,
                    FString::Printf(TEXT("%s[%d]"), *PropertyPath, Index),
                    Depth + 1, PropertyWriter, ReferenceWriter, Counts))
                return false;
        }
    }

    return true;
}

static bool WriteClass(UClass* Class, UClass* NavAreaBase, FWriters& Writers, FCounts& Counts)
{
    if (!Class) return true;
    UObject* CDO = Class->GetDefaultObject();
    if (!CDO) return false;
    if (Class->HasAnyClassFlags(CLASS_Config))
        CDO->LoadConfig();

    const FString ClassPath = Class->GetPathName();
    const FString Kind = ClassKind(Class, NavAreaBase);
    TSharedRef<FJsonObject> ClassRow = MakeShared<FJsonObject>();
    ClassRow->SetStringField(TEXT("class_path"), ClassPath);
    ClassRow->SetStringField(TEXT("parent_class"), Class->GetSuperClass() ? Class->GetSuperClass()->GetPathName() : FString());
    ClassRow->SetStringField(TEXT("kind"), Kind);
    ClassRow->SetStringField(TEXT("cdo_path"), CDO->GetPathName());
    ClassRow->SetNumberField(TEXT("class_flags"), static_cast<double>(Class->GetClassFlags()));
    ClassRow->SetBoolField(TEXT("native"), Class->HasAnyClassFlags(CLASS_Native));
    ClassRow->SetBoolField(TEXT("config_class"), Class->HasAnyClassFlags(CLASS_Config));
    ClassRow->SetBoolField(TEXT("abstract"), Class->HasAnyClassFlags(CLASS_Abstract));
    if (!Writers.Classes.Write(ClassRow)) return false;
    ++Counts.Classes;
    if (Kind == TEXT("nav_area")) ++Counts.AreaClasses;

    for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::IncludeSuper); It; ++It)
    {
        const FProperty* Property = *It;
        if (!ShouldInspectProperty(Property)) continue;
        for (int32 StaticIndex = 0; StaticIndex < Property->ArrayDim; ++StaticIndex)
        {
            const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(CDO, StaticIndex);
            FString Path = Property->GetName();
            if (Property->ArrayDim > 1)
                Path += FString::Printf(TEXT("[%d]"), StaticIndex);
            if (!WritePropertyRecursive(
                    Property, ValuePtr, CDO, ClassPath, Property->GetName(), Path,
                    0, Writers.Properties, Writers.References, Counts))
                return false;
        }
    }
    return true;
}

static UClass* LoadClassPath(const TCHAR* Path)
{
    return StaticLoadClass(UObject::StaticClass(), nullptr, Path);
}

static bool WriteManifest(const FString& OutputDir, const FCounts& Counts, bool bSuccess, const FString& Error)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Root->SetBoolField(TEXT("success"), bSuccess);
    Root->SetStringField(TEXT("error"), Error);
    Root->SetBoolField(TEXT("diagnostic_only"), true);
    Root->SetBoolField(TEXT("semantic_promotion"), false);
    Root->SetBoolField(TEXT("schema_promotion"), false);
    Root->SetBoolField(TEXT("runtime_state_captured"), false);
    Root->SetBoolField(TEXT("generated_navmesh_instances_captured"), false);
    Root->SetBoolField(TEXT("generated_navmesh_promoted"), false);
    Root->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("capture_scope"), TEXT("native Navigation/AIModule class defaults and project-applied config only; no world placement duplication, navmesh tiles, path queries or runtime state"));

    TSharedRef<FJsonObject> CountObject = MakeShared<FJsonObject>();
    CountObject->SetNumberField(TEXT("classes"), Counts.Classes);
    CountObject->SetNumberField(TEXT("area_classes"), Counts.AreaClasses);
    CountObject->SetNumberField(TEXT("cdo_properties"), Counts.CDOProperties);
    CountObject->SetNumberField(TEXT("cdo_references"), Counts.CDOReferences);
    CountObject->SetNumberField(TEXT("config_properties"), Counts.ConfigProperties);
    CountObject->SetNumberField(TEXT("truncated_values"), Counts.TruncatedValues);
    CountObject->SetNumberField(TEXT("depth_limit_hits"), Counts.DepthLimitHits);
    CountObject->SetNumberField(TEXT("container_limit_hits"), Counts.ContainerLimitHits);
    CountObject->SetNumberField(TEXT("missing_expected_classes"), Counts.MissingExpectedClasses);
    Root->SetObjectField(TEXT("counts"), CountObject);

    TArray<TSharedPtr<FJsonValue>> Expected;
    for (const TCHAR* Path : ExpectedClassPaths)
        Expected.Add(MakeShared<FJsonValueString>(Path));
    Root->SetArrayField(TEXT("expected_classes"), Expected);

    FString Text;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
    if (!FJsonSerializer::Serialize(Root, Writer)) return false;
    return FFileHelper::SaveStringToFile(
        Text,
        *FPaths::Combine(OutputDir, TEXT("navigation_capture_manifest.json")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

} // namespace UnrealAssetToolNavigation

UUnrealAssetToolNavigationCommandlet::UUnrealAssetToolNavigationCommandlet()
{
    IsClient = false;
    IsServer = false;
    IsEditor = true;
    LogToConsole = true;
    ShowErrorCount = true;
}

int32 UUnrealAssetToolNavigationCommandlet::Main(const FString& Params)
{
    using namespace UnrealAssetToolNavigation;

    FString OutputDir;
    if (!FParse::Value(*Params, TEXT("Output="), OutputDir) || OutputDir.IsEmpty())
    {
        UE_LOG(LogTemp, Error, TEXT("UnrealAssetToolNavigation requires -Output=<directory>"));
        return 2;
    }
    OutputDir = FPaths::ConvertRelativePathToFull(OutputDir);
    IFileManager::Get().MakeDirectory(*OutputDir, true);

    FModuleManager::Get().LoadModule(TEXT("NavigationSystem"));
    FModuleManager::Get().LoadModule(TEXT("AIModule"));

    FWriters Writers;
    FCounts Counts;
    FString Error;
    if (!Writers.Open(OutputDir))
    {
        Error = TEXT("failed opening Navigation capture output streams");
        WriteManifest(OutputDir, Counts, false, Error);
        UE_LOG(LogTemp, Error, TEXT("%s"), *Error);
        return 3;
    }

    UClass* NavAreaBase = LoadClassPath(TEXT("/Script/NavigationSystem.NavArea"));
    TMap<FString, UClass*> Classes;
    for (const TCHAR* Path : ExpectedClassPaths)
    {
        if (UClass* Class = LoadClassPath(Path))
            Classes.Add(Class->GetPathName(), Class);
        else
            ++Counts.MissingExpectedClasses;
    }

    if (NavAreaBase)
    {
        TArray<UClass*> DerivedAreas;
        GetDerivedClasses(NavAreaBase, DerivedAreas, true);
        for (UClass* AreaClass : DerivedAreas)
        {
            if (AreaClass)
                Classes.Add(AreaClass->GetPathName(), AreaClass);
        }
    }

    TArray<FString> ClassPaths;
    Classes.GetKeys(ClassPaths);
    ClassPaths.Sort();
    for (const FString& ClassPath : ClassPaths)
    {
        if (!WriteClass(Classes[ClassPath], NavAreaBase, Writers, Counts))
        {
            Error = TEXT("failed writing Navigation class/default evidence: ") + ClassPath;
            Writers.Close();
            WriteManifest(OutputDir, Counts, false, Error);
            UE_LOG(LogTemp, Error, TEXT("%s"), *Error);
            return 4;
        }
    }

    if (!Writers.Close())
    {
        Error = TEXT("failed closing Navigation capture output streams");
        WriteManifest(OutputDir, Counts, false, Error);
        UE_LOG(LogTemp, Error, TEXT("%s"), *Error);
        return 5;
    }

    if (Counts.MissingExpectedClasses != 0)
    {
        Error = FString::Printf(TEXT("missing %lld expected UE 5.8 Navigation classes"), Counts.MissingExpectedClasses);
        WriteManifest(OutputDir, Counts, false, Error);
        UE_LOG(LogTemp, Error, TEXT("%s"), *Error);
        return 6;
    }

    if (!WriteManifest(OutputDir, Counts, true, FString()))
    {
        UE_LOG(LogTemp, Error, TEXT("failed writing Navigation capture manifest"));
        return 7;
    }

    UE_LOG(LogTemp, Display,
        TEXT("UnrealAssetToolNavigation captured %lld classes, %lld area classes, %lld CDO properties, %lld references, %lld config properties"),
        Counts.Classes, Counts.AreaClasses, Counts.CDOProperties, Counts.CDOReferences, Counts.ConfigProperties);
    return 0;
}
