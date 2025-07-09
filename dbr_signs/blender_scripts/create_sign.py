import bpy
import os

# --- Define Parameters ---
SIGN_WIDTH_X = 225
SIGN_DEPTH_Y = 275
SIGN_HEIGHT_Z = 25
BORDER_WIDTH = 10
RECESS_DEPTH = 6
LOGO_FILENAME = "sign_logo.png"
# IMPORTANT: Place the logo image in this directory, or change the path
IMAGE_DIR = r"C:\Users\tschmidt\Downloads"

# --- Function to ensure we are in Object Mode ---
def ensure_object_mode():
    """Checks if Blender is in Object Mode, and switches if not."""
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

def clean_scene():
    """Deletes all mesh objects, textures, and materials from the scene."""
    ensure_object_mode()
    
    # Select all mesh objects
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.object.select_by_type(type='MESH')
    bpy.ops.object.delete()

    # Clean up orphaned data
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)
    for block in bpy.data.textures:
        if block.users == 0:
            bpy.data.textures.remove(block)
    for block in bpy.data.images:
        if block.users == 0:
            bpy.data.images.remove(block)
    print("Scene has been cleaned.")


def create_sign_base():
    """Creates the main sign block with a recessed center."""
    print("Creating sign base...")
    # 1. Create the main block
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0,0,0))
    base = bpy.context.active_object
    base.name = "Sign_Base"
    bpy.context.view_layer.objects.active = base
    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
    base.dimensions = (SIGN_WIDTH_X, SIGN_DEPTH_Y, SIGN_HEIGHT_Z)
    base.location = (SIGN_WIDTH_X / 2, SIGN_DEPTH_Y / 2, SIGN_HEIGHT_Z / 2)
    bpy.ops.object.transform_apply(scale=True, location=True)

    print("Creating cutter")
    # 2. Create the cutter object for the recess
    cutter_width = SIGN_WIDTH_X - (2 * BORDER_WIDTH)
    cutter_depth = SIGN_DEPTH_Y - (2 * BORDER_WIDTH)
    cutter_height = RECESS_DEPTH + 1 # Needs to be deep enough to cut
    
    recess_floor_z = SIGN_HEIGHT_Z - RECESS_DEPTH
    
    # Fix cutter Z-position to intersect from top
    cutter_location = (
        SIGN_WIDTH_X / 2,
        SIGN_DEPTH_Y / 2,
        recess_floor_z + cutter_height / 2
    )

    bpy.ops.mesh.primitive_cube_add(size=1, location=cutter_location)
    cutter = bpy.context.active_object
    cutter.name = "Cutter"
    cutter.dimensions = (cutter_width, cutter_depth, cutter_height)
    bpy.ops.object.transform_apply(scale=True)

    print("Removing recess")
    # 3. Perform the boolean operation
    bpy.ops.object.mode_set(mode='OBJECT')
    bool_mod = base.modifiers.new(name="RecessCut", type='BOOLEAN')
    bool_mod.operation = 'DIFFERENCE'
    bool_mod.object = cutter
    bpy.context.view_layer.objects.active = base
    base.select_set(True)
    cutter.select_set(True)
    bpy.ops.object.modifier_apply(modifier=bool_mod.name)
    
    # 4. Clean up
    bpy.data.objects.remove(cutter, do_unlink=True)
    print("Sign base created successfully.")
    return base

def create_logo(image_path):
    """Imports the logo, converts it to 3D, and positions it."""
    print("Creating 3D logo...")
    if not os.path.exists(image_path):
        print(f"ERROR: Image not found at {image_path}")
        return None

    # 1. Import image as a plane (already has correct UVs)
    try:
        bpy.ops.preferences.addon_enable(module="io_import_images_as_planes")
    except Exception as e:
        print(f"Failed to enable 'Import Images as Planes': {e}")

    bpy.ops.import_image.to_plane(
        files=[{'name': os.path.basename(image_path)}],
        directory=os.path.dirname(image_path)
    )
    logo_plane = bpy.context.active_object
    logo_plane.name = "Logo_Mesh"

    # 2. Scale and position the logo plane
    img_aspect = logo_plane.dimensions.y / logo_plane.dimensions.x
    logo_width = SIGN_WIDTH_X - (2 * BORDER_WIDTH)
    logo_plane.dimensions = (logo_width, logo_width * img_aspect, 1)
    bpy.ops.object.transform_apply(scale=True)

    recess_floor_z = SIGN_HEIGHT_Z - RECESS_DEPTH
    # Dropping 1mm to lower noise below surface
    logo_plane.location = (SIGN_WIDTH_X / 2, SIGN_DEPTH_Y / 2, recess_floor_z - 1)
    bpy.ops.object.transform_apply(location=True)

    # 3. Add geometry: Subdivide for displacement detail
    print("Subdividing logo mesh for detail...")
    # Use SIMPLE subdivision to avoid rounded corners and the 'oval' effect.
    # Increase levels for higher quality.
    subdiv = logo_plane.modifiers.new(name="Subdiv", type='SUBSURF')
    subdiv.subdivision_type = 'SIMPLE'  # Prevents rounded shape
    subdiv.levels = 9  # Higher value for more detail
    subdiv.render_levels = 9
    bpy.ops.object.modifier_apply(modifier=subdiv.name)

    print(f"Logo mesh now has {len(logo_plane.data.vertices)} vertices.")

    # Note: A manual UV unwrap is not needed as import-as-planes creates them.

    # 4. Add displacement modifier with a simplified logic
    print("Applying displacement...")
    disp_mod = logo_plane.modifiers.new(name="LogoDisplace", type='DISPLACE')

    # Use the image texture directly without a color ramp
    img_tex = bpy.data.textures.new('LogoTexture', type='IMAGE')
    img_tex.image = bpy.data.images.load(image_path)

    # Use Mid-level and Strength to control displacement without inverting
    # Mid-level '1' means white areas of the image are the zero-point.
    # Negative strength displaces the black areas 'upwards'.
    disp_mod.texture = img_tex
    disp_mod.texture_coords = 'UV'  # Use the original, correct UVs
    disp_mod.strength = -RECESS_DEPTH + 1 # Positive strength to raise the logo
                                          # add 1 mm so scaled to top of model
    disp_mod.mid_level = 1                # Black (background) has no offset

    # 5. Apply the displacement
    bpy.context.view_layer.objects.active = logo_plane
    bpy.ops.object.modifier_apply(modifier=disp_mod.name)

    print("3D logo created successfully.")
    return logo_plane


def create_wood_grain():
    """Creates a new plane and displaces it with a downloaded texture."""
    print("Creating wood grain surface from Polyhaven texture...")

    # 1. Define dimensions and position
    recess_floor_z = SIGN_HEIGHT_Z - RECESS_DEPTH
    grain_width = SIGN_WIDTH_X - (2 * BORDER_WIDTH)
    grain_depth = SIGN_DEPTH_Y - (2 * BORDER_WIDTH)
    grain_location = (
        SIGN_WIDTH_X / 2, SIGN_DEPTH_Y / 2, recess_floor_z + 1.0
    )

    # 2. Create the plane
    bpy.ops.mesh.primitive_plane_add(size=1, location=grain_location)
    wood_plane = bpy.context.active_object
    wood_plane.name = "Wood_Grain_Surface"
    wood_plane.dimensions = (grain_width, grain_depth, 1)
    bpy.ops.object.transform_apply(scale=True)

    # 3. Subdivide for detail
    subdiv = wood_plane.modifiers.new(name="Subdiv", type='SUBSURF')
    subdiv.subdivision_type = 'SIMPLE'
    subdiv.levels = 9  # High detail for texture displacement
    bpy.ops.object.modifier_apply(modifier=subdiv.name)

    # 4. Apply displacement using the downloaded texture
    disp = wood_plane.modifiers.new(name="WoodGrainDisp", type='DISPLACE')

    # Find the displacement texture from the downloaded material
    # The texture usually contains 'disp' or 'Displacement' in its name
    disp_texture = None
    for tex in bpy.data.textures:
        if "fine_grained_wood" in tex.name and ("disp" in tex.name.lower() or "displacement" in tex.name.lower()):
            disp_texture = tex
            break
    
    if disp_texture:
        print(f"Found displacement texture: {disp_texture.name}")
        disp.texture = disp_texture
        disp.strength = 1.0  # Adjust strength as needed
        disp.texture_coords = 'UV'
        # Apply the modifier to make the geometry real
        bpy.ops.object.modifier_apply(modifier=disp.name)
        print("Wood grain surface created successfully.")
        return wood_plane
    else:
        print("ERROR: Could not find the displacement texture for 'fine_grained_wood'.")
        # Clean up the created plane if texture is not found
        bpy.data.objects.remove(wood_plane, do_unlink=True)
        return None


def main():
    """Main function to run the entire sign creation process."""
    clean_scene()

    sign_base = create_sign_base()
    if not sign_base:
        return

    logo_path = os.path.join(IMAGE_DIR, LOGO_FILENAME)
    logo_mesh = create_logo(logo_path)
    if not logo_mesh:
        return

    # Create the wood grain as a separate object
    wood_grain_mesh = create_wood_grain()
    if not wood_grain_mesh:
        return

    # Final Join of all parts
    ensure_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    sign_base.select_set(True)
    logo_mesh.select_set(True)
    wood_grain_mesh.select_set(True)
    bpy.context.view_layer.objects.active = sign_base
    bpy.ops.object.join()

    final_sign = bpy.context.active_object
    final_sign.name = "Carvable_Sign"

    print("\n--- Process Complete ---")
    print("A single 'Carvable_Sign' object has been created.")


# --- Run the main function ---
if __name__ == "__main__":
    main() 