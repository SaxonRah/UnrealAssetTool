#include "UnrealAssetToolNativeScanner.h"

#include "HAL/FileManager.h"
#include "Json.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/Class.h"
#include "UObject/Field.h"
#include "UObject/UObjectIterator.h"
#include "UObject/UnrealType.h"

namespace UnrealAssetToolNative
{
namespace
{
constexpr const TCHAR* ManifestName = TEXT("native_manifest.json");

const TCHAR* const StreamNames[] = {
    TEXT("native_modules.jsonl"),
    TEXT("native_types.jsonl"),
    TEXT("native_interfaces.jsonl"),
    TEXT("native_functions.jsonl"),
    TEXT("native_function_parameters.jsonl"),
    TEXT("native_properties.jsonl"),
    TEXT("native_enums.jsonl"),
    TEXT("native_enum_values.jsonl"),
};

const TCHAR* const UFieldMetadataKeys[] = {
    TEXT("ModuleRelativePath"),
    TEXT("Category"),
    TEXT("DisplayName"),
    TEXT("ToolTip"),
    TEXT("BlueprintType"),
    TEXT("Blueprintable"),
    TEXT("NotBlueprintable"),
    TEXT("BlueprintSpawnableComponent"),
    TEXT("BlueprintInternalUseOnly"),
    TEXT("BlueprintAuthorityOnly"),
    TEXT("BlueprintCosmetic"),
    TEXT("WorldContext"),
    TEXT("DefaultToSelf"),
    TEXT("HidePin"),
    TEXT("InternalUseParam"),
    TEXT("AutoCreateRefTerm"),
    TEXT("DeterminesOutputType"),
    TEXT("DynamicOutputParam"),
    TEXT("Latent"),
    TEXT("LatentInfo"),
    TEXT("DeprecatedFunction"),
    TEXT("DeprecationMessage"),
    TEXT("DevelopmentOnly"),
};

const TCHAR* const FFieldMetadataKeys[] = {
    TEXT("Category"),
    TEXT("DisplayName"),
    TEXT("ToolTip"),
    TEXT("ModuleRelativePath"),
    TEXT("EditCondition"),
    TEXT("ClampMin"),
    TEXT("ClampMax"),
    TEXT("UIMin"),
    TEXT("UIMax"),
    TEXT("Units"),
    TEXT("AllowedClasses"),
    TEXT("DisallowedClasses"),
    TEXT("GetOptions"),
    TEXT("ExposeOnSpawn"),
    TEXT("AllowPrivateAccess"),
    TEXT("BlueprintReadOnly"),
    TEXT("BlueprintGetter"),
    TEXT("BlueprintSetter"),
};

struct FModuleRecord
{
    FString Name;
    FString BuildCs;
    FString OwnerKind;
    FString OwnerName;
    bool bLoaded = false;
};

struct FCounts
{
    int64 Modules = 0;
    int64 LoadedModules = 0;
    int64 Types = 0;
    int64 Classes = 0;
    int64 Structs = 0;
    int64 Interfaces = 0;
    int64 Functions = 0;
    int64 FunctionParameters = 0;
    int64 Properties = 0;
    int64 Enums = 0;
    int64 EnumValues = 0;
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
        if (!Archive.IsValid())
        {
            return false;
        }

        FString Line;
        const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
            TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);
        if (!FJsonSerializer::Serialize(Object, Writer))
        {
            return false;
        }

        Line.AppendChar(TEXT('\n'));
        FTCHARToUTF8 Utf8(*Line);
        Archive->Serialize((void*)Utf8.Get(), Utf8.Length());
        return !Archive->IsError();
    }

    bool Close()
    {
        if (!Archive.IsValid())
        {
            return true;
        }

        const bool bClosed = Archive->Close();
        const bool bOk = bClosed && !Archive->IsError();
        Archive.Reset();
        return bOk;
    }

    ~FJsonlWriter()
    {
        Close();
    }

private:
    TUniquePtr<FArchive> Archive;
};

struct FWriters
{
    FJsonlWriter Modules;
    FJsonlWriter Types;
    FJsonlWriter Interfaces;
    FJsonlWriter Functions;
    FJsonlWriter FunctionParameters;
    FJsonlWriter Properties;
    FJsonlWriter Enums;
    FJsonlWriter EnumValues;

    bool Open(const FString& OutputDir)
    {
        return
            Modules.Open(FPaths::Combine(OutputDir, TEXT("native_modules.jsonl"))) &&
            Types.Open(FPaths::Combine(OutputDir, TEXT("native_types.jsonl"))) &&
            Interfaces.Open(FPaths::Combine(OutputDir, TEXT("native_interfaces.jsonl"))) &&
            Functions.Open(FPaths::Combine(OutputDir, TEXT("native_functions.jsonl"))) &&
            FunctionParameters.Open(FPaths::Combine(OutputDir, TEXT("native_function_parameters.jsonl"))) &&
            Properties.Open(FPaths::Combine(OutputDir, TEXT("native_properties.jsonl"))) &&
            Enums.Open(FPaths::Combine(OutputDir, TEXT("native_enums.jsonl"))) &&
            EnumValues.Open(FPaths::Combine(OutputDir, TEXT("native_enum_values.jsonl")));
    }

    bool Close()
    {
        bool bOk = true;
        bOk = Modules.Close() && bOk;
        bOk = Types.Close() && bOk;
        bOk = Interfaces.Close() && bOk;
        bOk = Functions.Close() && bOk;
        bOk = FunctionParameters.Close() && bOk;
        bOk = Properties.Close() && bOk;
        bOk = Enums.Close() && bOk;
        bOk = EnumValues.Close() && bOk;
        return bOk;
    }
};

static FString NormalizePath(const FString& InPath)
{
    FString Result = FPaths::ConvertRelativePathToFull(InPath);
    FPaths::NormalizeFilename(Result);
    return Result;
}

static FString RelativeToProject(const FString& ProjectDir, const FString& Filename)
{
    FString Relative = NormalizePath(Filename);
    FString Base = NormalizePath(ProjectDir);
    if (!Base.EndsWith(TEXT("/")))
    {
        Base.AppendChar(TEXT('/'));
    }
    FPaths::MakePathRelativeTo(Relative, *Base);
    FPaths::NormalizeFilename(Relative);
    return Relative;
}

static bool IsUnder(const FString& Filename, const FString& Directory)
{
    if (Directory.IsEmpty())
    {
        return false;
    }
    return FPaths::IsUnderDirectory(NormalizePath(Filename), NormalizePath(Directory));
}

static FString Hex64(uint64 Value)
{
    return FString::Printf(TEXT("0x%016llX"), static_cast<unsigned long long>(Value));
}

static FString ModuleNameForObject(const UObject* Object)
{
    if (!Object || !Object->GetOutermost())
    {
        return FString();
    }

    const FString PackageName = Object->GetOutermost()->GetName();
    static const FString Prefix(TEXT("/Script/"));
    return PackageName.StartsWith(Prefix, ESearchCase::CaseSensitive)
        ? PackageName.Mid(Prefix.Len())
        : FString();
}

static bool IsAllowedModule(const UObject* Object, const TMap<FString, FModuleRecord>& Modules)
{
    const FString ModuleName = ModuleNameForObject(Object);
    return !ModuleName.IsEmpty() && Modules.Contains(ModuleName);
}

static TSharedRef<FJsonObject> UFieldMetadata(const UField* Field)
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    if (!Field)
    {
        return Result;
    }

    for (const TCHAR* Key : UFieldMetadataKeys)
    {
        if (const FString* Value = Field->FindMetaData(Key))
        {
            Result->SetStringField(Key, *Value);
        }
    }
    return Result;
}

static TSharedRef<FJsonObject> FFieldMetadata(const FField* Field)
{
    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    if (!Field)
    {
        return Result;
    }

    for (const TCHAR* Key : FFieldMetadataKeys)
    {
        if (Field->HasMetaData(Key))
        {
            Result->SetStringField(Key, Field->GetMetaData(Key));
        }
    }
    return Result;
}

static void AddReferencedType(TSet<FString>& OutTypes, const UObject* Object)
{
    if (Object)
    {
        OutTypes.Add(Object->GetPathName());
    }
}

static void CollectReferencedTypes(const FProperty* Property, TSet<FString>& OutTypes)
{
    if (!Property)
    {
        return;
    }

    if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
    {
        AddReferencedType(OutTypes, StructProperty->Struct);
    }
    if (const FEnumProperty* EnumProperty = CastField<FEnumProperty>(Property))
    {
        AddReferencedType(OutTypes, EnumProperty->GetEnum());
    }
    if (const FByteProperty* ByteProperty = CastField<FByteProperty>(Property))
    {
        AddReferencedType(OutTypes, ByteProperty->Enum);
    }
    if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
    {
        AddReferencedType(OutTypes, ObjectProperty->PropertyClass);
    }
    if (const FInterfaceProperty* InterfaceProperty = CastField<FInterfaceProperty>(Property))
    {
        AddReferencedType(OutTypes, InterfaceProperty->InterfaceClass);
    }
    if (const FDelegateProperty* DelegateProperty = CastField<FDelegateProperty>(Property))
    {
        AddReferencedType(OutTypes, DelegateProperty->SignatureFunction);
    }
    if (const FMulticastDelegateProperty* DelegateProperty = CastField<FMulticastDelegateProperty>(Property))
    {
        AddReferencedType(OutTypes, DelegateProperty->SignatureFunction);
    }
    if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
    {
        CollectReferencedTypes(ArrayProperty->Inner, OutTypes);
    }
    if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
    {
        CollectReferencedTypes(SetProperty->ElementProp, OutTypes);
    }
    if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
    {
        CollectReferencedTypes(MapProperty->KeyProp, OutTypes);
        CollectReferencedTypes(MapProperty->ValueProp, OutTypes);
    }
}

static FString ContainerKind(const FProperty* Property)
{
    if (CastField<FArrayProperty>(Property)) return TEXT("array");
    if (CastField<FSetProperty>(Property)) return TEXT("set");
    if (CastField<FMapProperty>(Property)) return TEXT("map");
    return FString();
}

static TArray<TSharedPtr<FJsonValue>> ReferencedTypeArray(const FProperty* Property)
{
    TSet<FString> Seen;
    CollectReferencedTypes(Property, Seen);
    TArray<FString> Values = Seen.Array();
    Values.Sort();

    TArray<TSharedPtr<FJsonValue>> Result;
    Result.Reserve(Values.Num());
    for (const FString& Value : Values)
    {
        Result.Add(MakeShared<FJsonValueString>(Value));
    }
    return Result;
}

static void AddPropertyShape(const FProperty* Property, const TSharedRef<FJsonObject>& Row)
{
    Row->SetStringField(TEXT("property_class"), Property ? Property->GetClass()->GetName() : FString());
    Row->SetStringField(TEXT("cpp_type"), Property ? Property->GetCPPType() : FString());
    Row->SetStringField(TEXT("container_kind"), ContainerKind(Property));
    Row->SetNumberField(TEXT("array_dim"), Property ? Property->ArrayDim : 0);
    Row->SetNumberField(TEXT("element_size"), Property ? Property->ElementSize : 0);
    Row->SetStringField(
        TEXT("property_flags_hex"),
        Property ? Hex64(static_cast<uint64>(Property->GetPropertyFlags())) : Hex64(0));
    Row->SetArrayField(TEXT("referenced_types"), ReferencedTypeArray(Property));
    Row->SetObjectField(TEXT("metadata"), FFieldMetadata(Property));

    if (!Property)
    {
        return;
    }

    Row->SetBoolField(TEXT("edit"), Property->HasAnyPropertyFlags(CPF_Edit));
    Row->SetBoolField(TEXT("blueprint_visible"), Property->HasAnyPropertyFlags(CPF_BlueprintVisible));
    Row->SetBoolField(TEXT("blueprint_read_only"), Property->HasAnyPropertyFlags(CPF_BlueprintReadOnly));
    Row->SetBoolField(TEXT("config"), Property->HasAnyPropertyFlags(CPF_Config));
    Row->SetBoolField(TEXT("net"), Property->HasAnyPropertyFlags(CPF_Net));
    Row->SetBoolField(TEXT("rep_notify"), Property->HasAnyPropertyFlags(CPF_RepNotify));
    Row->SetBoolField(TEXT("transient"), Property->HasAnyPropertyFlags(CPF_Transient));
    Row->SetBoolField(TEXT("save_game"), Property->HasAnyPropertyFlags(CPF_SaveGame));
    Row->SetBoolField(TEXT("instanced_reference"), Property->HasAnyPropertyFlags(CPF_InstancedReference));
    Row->SetBoolField(TEXT("expose_on_spawn"), Property->HasAnyPropertyFlags(CPF_ExposeOnSpawn));
    Row->SetBoolField(TEXT("parameter"), Property->HasAnyPropertyFlags(CPF_Parm));
    Row->SetBoolField(TEXT("out_parameter"), Property->HasAnyPropertyFlags(CPF_OutParm));
    Row->SetBoolField(TEXT("reference_parameter"), Property->HasAnyPropertyFlags(CPF_ReferenceParm));
    Row->SetBoolField(TEXT("const_parameter"), Property->HasAnyPropertyFlags(CPF_ConstParm));
    Row->SetBoolField(TEXT("return_parameter"), Property->HasAnyPropertyFlags(CPF_ReturnParm));
}

static FString FunctionAccess(const UFunction* Function)
{
    if (!Function) return FString();
    if (Function->HasAnyFunctionFlags(FUNC_Public)) return TEXT("public");
    if (Function->HasAnyFunctionFlags(FUNC_Protected)) return TEXT("protected");
    if (Function->HasAnyFunctionFlags(FUNC_Private)) return TEXT("private");
    return FString();
}

static TMap<FString, FModuleRecord> DiscoverModules(
    const FString& ProjectDir,
    const FString& ToolPluginDir)
{
    TArray<FString> BuildFiles;
    IFileManager::Get().FindFilesRecursive(
        BuildFiles,
        *FPaths::Combine(ProjectDir, TEXT("Source")),
        TEXT("*.Build.cs"),
        true,
        false,
        false);
    IFileManager::Get().FindFilesRecursive(
        BuildFiles,
        *FPaths::Combine(ProjectDir, TEXT("Plugins")),
        TEXT("*.Build.cs"),
        true,
        false,
        false);

    BuildFiles.Sort();

    TMap<FString, FModuleRecord> Modules;
    for (const FString& BuildFileRaw : BuildFiles)
    {
        const FString BuildFile = NormalizePath(BuildFileRaw);
        if (!ToolPluginDir.IsEmpty() && IsUnder(BuildFile, ToolPluginDir))
        {
            continue;
        }

        FString Filename = FPaths::GetCleanFilename(BuildFile);
        if (!Filename.EndsWith(TEXT(".Build.cs"), ESearchCase::CaseSensitive))
        {
            continue;
        }

        Filename.LeftChopInline(9, EAllowShrinking::No);
        if (Filename.IsEmpty())
        {
            continue;
        }

        FModuleRecord Record;
        Record.Name = Filename;
        Record.BuildCs = RelativeToProject(ProjectDir, BuildFile);
        Record.OwnerKind = TEXT("project");
        Record.OwnerName = FApp::GetProjectName();

        const FString NormalizedRelative = Record.BuildCs.Replace(TEXT("\\"), TEXT("/"));
        static const FString PluginsPrefix(TEXT("Plugins/"));
        if (NormalizedRelative.StartsWith(PluginsPrefix, ESearchCase::IgnoreCase))
        {
            FString Tail = NormalizedRelative.Mid(PluginsPrefix.Len());
            FString PluginName;
            FString Remainder;
            if (Tail.Split(TEXT("/"), &PluginName, &Remainder))
            {
                Record.OwnerKind = TEXT("project_plugin");
                Record.OwnerName = PluginName;
            }
        }

        Record.bLoaded = FModuleManager::Get().IsModuleLoaded(FName(*Record.Name));
        Modules.Add(Record.Name, MoveTemp(Record));
    }

    return Modules;
}

static bool WriteModules(
    const TMap<FString, FModuleRecord>& Modules,
    FJsonlWriter& Writer,
    FCounts& Counts)
{
    TArray<FString> Names;
    Modules.GetKeys(Names);
    Names.Sort();

    for (const FString& Name : Names)
    {
        const FModuleRecord& Module = Modules[Name];
        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("module_name"), Module.Name);
        Row->SetStringField(TEXT("build_cs"), Module.BuildCs);
        Row->SetStringField(TEXT("owner_kind"), Module.OwnerKind);
        Row->SetStringField(TEXT("owner_name"), Module.OwnerName);
        Row->SetBoolField(TEXT("loaded"), Module.bLoaded);
        if (!Writer.Write(Row))
        {
            return false;
        }

        ++Counts.Modules;
        if (Module.bLoaded)
        {
            ++Counts.LoadedModules;
        }
    }
    return true;
}

static bool WriteTypeProperties(
    const UStruct* Struct,
    const FString& OwnerKind,
    const FString& OwnerPath,
    FJsonlWriter& Writer,
    FCounts& Counts)
{
    int32 DeclarationIndex = 0;
    for (TFieldIterator<FProperty> It(Struct, EFieldIterationFlags::ExcludeSuper); It; ++It)
    {
        const FProperty* Property = *It;
        if (!Property || Property->HasAnyPropertyFlags(CPF_Parm))
        {
            continue;
        }

        TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
        Row->SetStringField(TEXT("owner_kind"), OwnerKind);
        Row->SetStringField(TEXT("owner_path"), OwnerPath);
        Row->SetStringField(TEXT("property_name"), Property->GetName());
        Row->SetNumberField(TEXT("declaration_index"), DeclarationIndex++);
        AddPropertyShape(Property, Row);
        if (!Writer.Write(Row))
        {
            return false;
        }
        ++Counts.Properties;
    }
    return true;
}

static bool WriteClass(
    UClass* Class,
    FWriters& Writers,
    FCounts& Counts)
{
    const FString ClassPath = Class->GetPathName();
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("type_path"), ClassPath);
    Row->SetStringField(TEXT("module_name"), ModuleNameForObject(Class));
    Row->SetStringField(TEXT("kind"), TEXT("class"));
    Row->SetStringField(TEXT("name"), Class->GetName());
    Row->SetStringField(TEXT("cpp_name"), FString(Class->GetPrefixCPP()) + Class->GetName());
    Row->SetStringField(
        TEXT("super_type"),
        Class->GetSuperClass() ? Class->GetSuperClass()->GetPathName() : FString());
    Row->SetStringField(
        TEXT("within_class"),
        Class->ClassWithin ? Class->ClassWithin->GetPathName() : FString());
    Row->SetStringField(TEXT("config_name"), Class->ClassConfigName.ToString());
    Row->SetNumberField(TEXT("structure_size"), Class->GetStructureSize());
    Row->SetNumberField(TEXT("min_alignment"), Class->GetMinAlignment());
    Row->SetStringField(TEXT("class_flags_hex"), Hex64(static_cast<uint64>(Class->GetClassFlags())));
    Row->SetBoolField(TEXT("native"), Class->HasAnyClassFlags(CLASS_Native));
    Row->SetBoolField(TEXT("abstract"), Class->HasAnyClassFlags(CLASS_Abstract));
    Row->SetBoolField(TEXT("interface"), Class->HasAnyClassFlags(CLASS_Interface));
    Row->SetBoolField(TEXT("config"), Class->HasAnyClassFlags(CLASS_Config));
    Row->SetBoolField(TEXT("default_config"), Class->HasAnyClassFlags(CLASS_DefaultConfig));
    Row->SetBoolField(TEXT("transient"), Class->HasAnyClassFlags(CLASS_Transient));
    Row->SetBoolField(TEXT("deprecated"), Class->HasAnyClassFlags(CLASS_Deprecated));
    Row->SetBoolField(TEXT("minimal_api"), Class->HasAnyClassFlags(CLASS_MinimalAPI));
    Row->SetObjectField(TEXT("metadata"), UFieldMetadata(Class));
    if (!Writers.Types.Write(Row))
    {
        return false;
    }

    ++Counts.Types;
    ++Counts.Classes;

    int32 InterfaceIndex = 0;
    for (const FImplementedInterface& Interface : Class->Interfaces)
    {
        TSharedRef<FJsonObject> InterfaceRow = MakeShared<FJsonObject>();
        InterfaceRow->SetStringField(TEXT("class_path"), ClassPath);
        InterfaceRow->SetNumberField(TEXT("interface_index"), InterfaceIndex++);
        InterfaceRow->SetStringField(
            TEXT("interface_class"),
            Interface.Class ? Interface.Class->GetPathName() : FString());
        InterfaceRow->SetNumberField(TEXT("pointer_offset"), Interface.PointerOffset);
        InterfaceRow->SetBoolField(TEXT("implemented_by_k2"), Interface.bImplementedByK2);
        if (!Writers.Interfaces.Write(InterfaceRow))
        {
            return false;
        }
        ++Counts.Interfaces;
    }

    return WriteTypeProperties(Class, TEXT("class"), ClassPath, Writers.Properties, Counts);
}

static bool WriteScriptStruct(
    UScriptStruct* Struct,
    FWriters& Writers,
    FCounts& Counts)
{
    const FString StructPath = Struct->GetPathName();
    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("type_path"), StructPath);
    Row->SetStringField(TEXT("module_name"), ModuleNameForObject(Struct));
    Row->SetStringField(TEXT("kind"), TEXT("script_struct"));
    Row->SetStringField(TEXT("name"), Struct->GetName());
    Row->SetStringField(TEXT("cpp_name"), Struct->GetStructCPPName(0));
    Row->SetStringField(
        TEXT("super_type"),
        Struct->GetSuperStruct() ? Struct->GetSuperStruct()->GetPathName() : FString());
    Row->SetNumberField(TEXT("structure_size"), Struct->GetStructureSize());
    Row->SetNumberField(TEXT("min_alignment"), Struct->GetMinAlignment());
    Row->SetStringField(TEXT("struct_flags_hex"), Hex64(static_cast<uint64>(Struct->StructFlags)));
    Row->SetBoolField(TEXT("native"), EnumHasAnyFlags(Struct->StructFlags, STRUCT_Native));
    Row->SetObjectField(TEXT("metadata"), UFieldMetadata(Struct));
    if (!Writers.Types.Write(Row))
    {
        return false;
    }

    ++Counts.Types;
    ++Counts.Structs;
    return WriteTypeProperties(Struct, TEXT("script_struct"), StructPath, Writers.Properties, Counts);
}

static FString ParameterKind(const FProperty* Property)
{
    if (!Property)
    {
        return FString();
    }
    if (Property->HasAnyPropertyFlags(CPF_ReturnParm))
    {
        return TEXT("return");
    }
    if (Property->HasAnyPropertyFlags(CPF_OutParm | CPF_ReferenceParm))
    {
        return TEXT("inout");
    }
    if (Property->HasAnyPropertyFlags(CPF_OutParm))
    {
        return TEXT("out");
    }
    return TEXT("input");
}

static bool WriteFunction(
    UFunction* Function,
    FWriters& Writers,
    FCounts& Counts)
{
    const FString FunctionPath = Function->GetPathName();
    const UObject* Owner = Function->GetOuter();

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("function_path"), FunctionPath);
    Row->SetStringField(TEXT("module_name"), ModuleNameForObject(Function));
    Row->SetStringField(TEXT("owner_path"), Owner ? Owner->GetPathName() : FString());
    Row->SetStringField(
        TEXT("owner_kind"),
        Cast<UClass>(Owner) ? TEXT("class") :
        Cast<UScriptStruct>(Owner) ? TEXT("script_struct") :
        TEXT("other"));
    Row->SetStringField(TEXT("name"), Function->GetName());
    Row->SetStringField(TEXT("access"), FunctionAccess(Function));
    Row->SetStringField(
        TEXT("function_flags_hex"),
        Hex64(static_cast<uint64>(Function->GetFunctionFlags())));
    Row->SetNumberField(TEXT("parameter_count"), Function->NumParms);
    Row->SetNumberField(TEXT("parameter_size"), Function->ParmsSize);
    Row->SetBoolField(TEXT("native"), Function->HasAnyFunctionFlags(FUNC_Native));
    Row->SetBoolField(TEXT("static"), Function->HasAnyFunctionFlags(FUNC_Static));
    Row->SetBoolField(TEXT("const"), Function->HasAnyFunctionFlags(FUNC_Const));
    Row->SetBoolField(TEXT("final"), Function->HasAnyFunctionFlags(FUNC_Final));
    Row->SetBoolField(TEXT("event"), Function->HasAnyFunctionFlags(FUNC_Event));
    Row->SetBoolField(TEXT("blueprint_event"), Function->HasAnyFunctionFlags(FUNC_BlueprintEvent));
    Row->SetBoolField(TEXT("blueprint_callable"), Function->HasAnyFunctionFlags(FUNC_BlueprintCallable));
    Row->SetBoolField(TEXT("blueprint_pure"), Function->HasAnyFunctionFlags(FUNC_BlueprintPure));
    Row->SetBoolField(TEXT("blueprint_authority_only"), Function->HasAnyFunctionFlags(FUNC_BlueprintAuthorityOnly));
    Row->SetBoolField(TEXT("blueprint_cosmetic"), Function->HasAnyFunctionFlags(FUNC_BlueprintCosmetic));
    Row->SetBoolField(TEXT("exec"), Function->HasAnyFunctionFlags(FUNC_Exec));
    Row->SetBoolField(TEXT("delegate"), Function->HasAnyFunctionFlags(FUNC_Delegate));
    Row->SetBoolField(TEXT("multicast_delegate"), Function->HasAnyFunctionFlags(FUNC_MulticastDelegate));
    Row->SetBoolField(TEXT("net"), Function->HasAnyFunctionFlags(FUNC_Net));
    Row->SetBoolField(TEXT("net_reliable"), Function->HasAnyFunctionFlags(FUNC_NetReliable));
    Row->SetBoolField(TEXT("net_server"), Function->HasAnyFunctionFlags(FUNC_NetServer));
    Row->SetBoolField(TEXT("net_client"), Function->HasAnyFunctionFlags(FUNC_NetClient));
    Row->SetBoolField(TEXT("net_multicast"), Function->HasAnyFunctionFlags(FUNC_NetMulticast));
    Row->SetObjectField(TEXT("metadata"), UFieldMetadata(Function));
    if (!Writers.Functions.Write(Row))
    {
        return false;
    }
    ++Counts.Functions;

    int32 ParameterIndex = 0;
    for (TFieldIterator<FProperty> It(Function, EFieldIterationFlags::ExcludeSuper); It; ++It)
    {
        const FProperty* Property = *It;
        if (!Property || !Property->HasAnyPropertyFlags(CPF_Parm))
        {
            continue;
        }

        TSharedRef<FJsonObject> ParameterRow = MakeShared<FJsonObject>();
        ParameterRow->SetStringField(TEXT("function_path"), FunctionPath);
        ParameterRow->SetNumberField(TEXT("parameter_index"), ParameterIndex++);
        ParameterRow->SetStringField(TEXT("parameter_name"), Property->GetName());
        ParameterRow->SetStringField(TEXT("parameter_kind"), ParameterKind(Property));
        AddPropertyShape(Property, ParameterRow);
        if (!Writers.FunctionParameters.Write(ParameterRow))
        {
            return false;
        }
        ++Counts.FunctionParameters;
    }

    return true;
}

static FString EnumCppForm(const UEnum* Enum)
{
    if (!Enum)
    {
        return FString();
    }

    switch (Enum->GetCppForm())
    {
    case UEnum::ECppForm::Regular:
        return TEXT("regular");
    case UEnum::ECppForm::Namespaced:
        return TEXT("namespaced");
    case UEnum::ECppForm::EnumClass:
        return TEXT("enum_class");
    default:
        return TEXT("unknown");
    }
}

static bool WriteEnum(
    UEnum* Enum,
    FWriters& Writers,
    FCounts& Counts)
{
    const FString EnumPath = Enum->GetPathName();

    TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
    Row->SetStringField(TEXT("enum_path"), EnumPath);
    Row->SetStringField(TEXT("module_name"), ModuleNameForObject(Enum));
    Row->SetStringField(TEXT("name"), Enum->GetName());
    Row->SetStringField(TEXT("cpp_type"), Enum->GetCppType());
    Row->SetStringField(TEXT("cpp_form"), EnumCppForm(Enum));
    Row->SetNumberField(TEXT("value_count"), Enum->NumEnums());
    Row->SetObjectField(TEXT("metadata"), UFieldMetadata(Enum));
    if (!Writers.Enums.Write(Row))
    {
        return false;
    }
    ++Counts.Enums;

    for (int32 Index = 0; Index < Enum->NumEnums(); ++Index)
    {
        TSharedRef<FJsonObject> ValueRow = MakeShared<FJsonObject>();
        ValueRow->SetStringField(TEXT("enum_path"), EnumPath);
        ValueRow->SetNumberField(TEXT("value_index"), Index);
        ValueRow->SetStringField(TEXT("name"), Enum->GetNameStringByIndex(Index));
        ValueRow->SetStringField(TEXT("full_name"), Enum->GetNameByIndex(Index).ToString());
        ValueRow->SetNumberField(TEXT("value"), static_cast<double>(Enum->GetValueByIndex(Index)));
        ValueRow->SetStringField(TEXT("display_name"), Enum->GetDisplayNameTextByIndex(Index).ToString());
        ValueRow->SetBoolField(TEXT("hidden"), Enum->HasMetaData(TEXT("Hidden"), Index));
        ValueRow->SetStringField(TEXT("tooltip"), Enum->GetMetaData(TEXT("ToolTip"), Index));
        if (!Writers.EnumValues.Write(ValueRow))
        {
            return false;
        }
        ++Counts.EnumValues;
    }

    return true;
}

static bool SaveManifest(
    const FString& OutputDir,
    const TMap<FString, FModuleRecord>& Modules,
    const FCounts& Counts,
    bool bSuccess,
    const FString& Error)
{
    TSharedRef<FJsonObject> Manifest = MakeShared<FJsonObject>();
    Manifest->SetNumberField(TEXT("schema_version"), SchemaVersion);
    Manifest->SetStringField(TEXT("pass"), TEXT("UnrealAssetToolNative"));
    Manifest->SetBoolField(TEXT("success"), bSuccess);
    Manifest->SetStringField(TEXT("error"), Error);
    Manifest->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
    Manifest->SetStringField(
        TEXT("capture_scope"),
        TEXT("project and project-plugin reflected native C++ declarations only; ordinary non-reflected C/C++ source semantics are not claimed"));

    TArray<TSharedPtr<FJsonValue>> Files;
    for (const TCHAR* Name : StreamNames)
    {
        Files.Add(MakeShared<FJsonValueString>(Name));
    }
    Manifest->SetArrayField(TEXT("files"), Files);

    TArray<FString> ModuleNames;
    Modules.GetKeys(ModuleNames);
    ModuleNames.Sort();
    TArray<TSharedPtr<FJsonValue>> ModuleValues;
    for (const FString& ModuleName : ModuleNames)
    {
        ModuleValues.Add(MakeShared<FJsonValueString>(ModuleName));
    }
    Manifest->SetArrayField(TEXT("modules"), ModuleValues);

    TSharedRef<FJsonObject> CountObject = MakeShared<FJsonObject>();
    CountObject->SetNumberField(TEXT("modules"), Counts.Modules);
    CountObject->SetNumberField(TEXT("loaded_modules"), Counts.LoadedModules);
    CountObject->SetNumberField(TEXT("types"), Counts.Types);
    CountObject->SetNumberField(TEXT("classes"), Counts.Classes);
    CountObject->SetNumberField(TEXT("structs"), Counts.Structs);
    CountObject->SetNumberField(TEXT("interfaces"), Counts.Interfaces);
    CountObject->SetNumberField(TEXT("functions"), Counts.Functions);
    CountObject->SetNumberField(TEXT("function_parameters"), Counts.FunctionParameters);
    CountObject->SetNumberField(TEXT("properties"), Counts.Properties);
    CountObject->SetNumberField(TEXT("enums"), Counts.Enums);
    CountObject->SetNumberField(TEXT("enum_values"), Counts.EnumValues);
    Manifest->SetObjectField(TEXT("counts"), CountObject);

    FString Text;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
    if (!FJsonSerializer::Serialize(Manifest, Writer))
    {
        return false;
    }

    return FFileHelper::SaveStringToFile(
        Text + TEXT("\n"),
        *FPaths::Combine(OutputDir, ManifestName),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
}

} // namespace

bool Scan(
    const FString& ProjectDir,
    const FString& ToolPluginDir,
    const FString& OutputDir,
    FString& OutError)
{
    OutError.Reset();
    const TMap<FString, FModuleRecord> Modules = DiscoverModules(ProjectDir, ToolPluginDir);

    FWriters Writers;
    FCounts Counts;

    if (!Writers.Open(OutputDir))
    {
        OutError = TEXT("failed opening native C++ schema-1 output streams");
        SaveManifest(OutputDir, Modules, Counts, false, OutError);
        return false;
    }

    if (!WriteModules(Modules, Writers.Modules, Counts))
    {
        OutError = TEXT("failed writing native module inventory");
        Writers.Close();
        SaveManifest(OutputDir, Modules, Counts, false, OutError);
        return false;
    }

    TMap<FString, UClass*> Classes;
    for (TObjectIterator<UClass> It; It; ++It)
    {
        UClass* Class = *It;
        if (Class && IsAllowedModule(Class, Modules))
        {
            Classes.Add(Class->GetPathName(), Class);
        }
    }

    TArray<FString> ClassPaths;
    Classes.GetKeys(ClassPaths);
    ClassPaths.Sort();
    for (const FString& Path : ClassPaths)
    {
        if (!WriteClass(Classes[Path], Writers, Counts))
        {
            OutError = TEXT("failed writing native class: ") + Path;
            Writers.Close();
            SaveManifest(OutputDir, Modules, Counts, false, OutError);
            return false;
        }
    }

    TMap<FString, UScriptStruct*> Structs;
    for (TObjectIterator<UScriptStruct> It; It; ++It)
    {
        UScriptStruct* Struct = *It;
        if (Struct && IsAllowedModule(Struct, Modules))
        {
            Structs.Add(Struct->GetPathName(), Struct);
        }
    }

    TArray<FString> StructPaths;
    Structs.GetKeys(StructPaths);
    StructPaths.Sort();
    for (const FString& Path : StructPaths)
    {
        if (!WriteScriptStruct(Structs[Path], Writers, Counts))
        {
            OutError = TEXT("failed writing native script struct: ") + Path;
            Writers.Close();
            SaveManifest(OutputDir, Modules, Counts, false, OutError);
            return false;
        }
    }

    TMap<FString, UFunction*> Functions;
    for (TObjectIterator<UFunction> It; It; ++It)
    {
        UFunction* Function = *It;
        if (Function && IsAllowedModule(Function, Modules))
        {
            Functions.Add(Function->GetPathName(), Function);
        }
    }

    TArray<FString> FunctionPaths;
    Functions.GetKeys(FunctionPaths);
    FunctionPaths.Sort();
    for (const FString& Path : FunctionPaths)
    {
        if (!WriteFunction(Functions[Path], Writers, Counts))
        {
            OutError = TEXT("failed writing native function: ") + Path;
            Writers.Close();
            SaveManifest(OutputDir, Modules, Counts, false, OutError);
            return false;
        }
    }

    TMap<FString, UEnum*> Enums;
    for (TObjectIterator<UEnum> It; It; ++It)
    {
        UEnum* Enum = *It;
        if (Enum && IsAllowedModule(Enum, Modules))
        {
            Enums.Add(Enum->GetPathName(), Enum);
        }
    }

    TArray<FString> EnumPaths;
    Enums.GetKeys(EnumPaths);
    EnumPaths.Sort();
    for (const FString& Path : EnumPaths)
    {
        if (!WriteEnum(Enums[Path], Writers, Counts))
        {
            OutError = TEXT("failed writing native enum: ") + Path;
            Writers.Close();
            SaveManifest(OutputDir, Modules, Counts, false, OutError);
            return false;
        }
    }

    if (!Writers.Close())
    {
        OutError = TEXT("failed closing native C++ schema-1 output streams");
        SaveManifest(OutputDir, Modules, Counts, false, OutError);
        return false;
    }

    if (!SaveManifest(OutputDir, Modules, Counts, true, FString()))
    {
        OutError = TEXT("failed writing native_manifest.json");
        return false;
    }

    UE_LOG(
        LogTemp,
        Display,
        TEXT("UnrealAssetTool native: modules=%lld loaded=%lld classes=%lld structs=%lld functions=%lld properties=%lld enums=%lld"),
        Counts.Modules,
        Counts.LoadedModules,
        Counts.Classes,
        Counts.Structs,
        Counts.Functions,
        Counts.Properties,
        Counts.Enums);

    return true;
}

} // namespace UnrealAssetToolNative
