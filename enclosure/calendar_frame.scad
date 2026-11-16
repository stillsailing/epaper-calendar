// 3D-printable frame for the e-paper calendar (GDEP073E01 + DESPI-C73 + ESP32-L).
// Units: mm. X = the panel's long edge, Y = its short edge, Z = depth from the
// front face (Z = 0 is the viewing side). Measurements and assumptions are
// recorded in docs/enclosure.md; values marked "not measured" must be checked
// against the real parts before printing.
//
// Export one part at a time, e.g.:
//   openscad -D 'part="frame"' -o .build/enclosure/frame.stl enclosure/calendar_frame.scad
//
// Stack, front to back: frame face | panel | foam tape | plate (boards on its
// back) | free space | lid. The lid is screwed to the frame's corner bosses
// and presses the plate's pillars, which clamp the panel through the foam.

part = "assembly"; // [assembly, exploded, frame, plate, lid, foot, panel, boards, keypad]
// true: export each part at its assembly position (used by build_viewer.py).
placed = false;

/* [Panel: measured] */
panel_w = 170.2;
panel_h = 111.2;
panel_t = 0.91;

/* [Panel: active area, not measured] */
active_w = 160.0;
active_h = 96.0;
// Active-area offset from the panel's left edge and from its bottom (FPC) edge.
active_x = (panel_w - active_w) / 2;
active_y = (panel_h - active_h) / 2;

/* [Flex cable, not measured] */
// The FPC is assumed to leave the panel's bottom edge.
fpc_w = 40;      // width of the gap left for it
fpc_x = 0;       // gap centre, relative to the panel centre
fpc_reach = 15;  // how far the plate opening extends behind the panel

/* [Frame] */
border = 12;          // frame width outside the panel pocket
face_t = 2.0;         // front face thickness
wall = 2.4;
corner_r = 4;
clear = 0.3;          // panel pocket clearance per side
window_margin = 0.8;  // window extends past the active area per side
lip_t = 1.2;          // ridge that locates the panel
foam_t = 1.0;         // foam tape between panel and plate
plate_t = 2.0;
electronics_h = 22;   // free depth behind the plate: boards, Dupont wires, battery
lid_t = 2.4;
fit = 0.3;            // gap between printed parts

/* [Screws: M3 self-tapping into the bosses] */
boss_d = 8;
pilot_d = 2.5;        // 4.0 for M3 heat-set inserts
pilot_depth = 12;
screw_d = 3.4;
screw_head_d = 6.4;
screw_head_t = 1.2;

/* [Boards on the plate, not measured] */
// [length, width, PCB thickness, lift under the PCB, x, y, rotation].
// Boards slide in between grooved rails from the -X end (keep the USB port
// there); the +X end has a stop.
esp32_board = [57, 26, 1.6, 3, 45, 15, 0];
adapter_board = [45, 30, 1.6, 3, -35, -10, 0];

/* [Buttons on the top edge, not measured] */
// The button module's PCB stands parallel to the top wall with its switches
// facing it. It slides into two grooved guides from the back; the lid holds
// it in. Seen from the front, left to right: wake, previous month, previous
// day, today, next day, next month, month view (docs/hardware.md). Frame X points
// to the viewer's left, so the largest offset is the leftmost key.
keypad_x = 0;                 // module centre along the top edge
keypad_w = 150;               // module PCB width, along the edge (about the panel width - 2 cm)
keypad_h = 20;                // module PCB height, front to back
keypad_pcb_t = 1.6;
key_offsets = [-60, -40, -20, 0, 20, 40, 60];  // keys to expose, X from the module centre
key_zoff = 10;                // key centre from the module's front edge
switch_h = 5;                 // PCB surface to the top of the switch stem
key_hole_d = 4.2;
key_wall = 1.2;               // wall thickness left in the button recess
key_proud = 0.5;              // stem past the thinned wall, still below the outer surface
keypad_guide_w = 3;

/* [Lid] */
cable_x = 0;          // USB cable notch along the bottom edge
cable_w = 8;
keyhole_dx = 50;      // wall-hanging keyholes, distance from the centre

/* [Stand] */
tilt = 15;            // lean back from vertical, degrees
foot_w = 20;
foot_d = 60;
foot_base = 3;

$fn = 48;

// Derived dimensions.
pocket_w = panel_w + 2 * clear;
pocket_h = panel_h + 2 * clear;
outer_w = pocket_w + 2 * border;
outer_h = pocket_h + 2 * border;
inner_w = outer_w - 2 * wall;
inner_h = outer_h - 2 * wall;
z_plate = face_t + panel_t + foam_t;
z_lid = z_plate + plate_t + electronics_h;
depth = z_lid + lid_t;
window_w = active_w + 2 * window_margin;
window_h = active_h + 2 * window_margin;
window_c = [-panel_w / 2 + active_x + active_w / 2, -panel_h / 2 + active_y + active_h / 2];
boss_xy = [inner_w / 2 - boss_d / 2, inner_h / 2 - boss_d / 2];
// Posts under the plate (and pillars above it), along the top and bottom
// edges between the panel ridge and the wall, clear of the FPC gap and the
// button module.
post_d = 6;
// Near the ends so the top pair stays clear of the button module.
post_xy = [pocket_w / 2 - 2, pocket_h / 2 + lip_t + 0.4 + post_d / 2];

// Button module, derived.
keypad_z0 = z_lid - fit - keypad_h;  // module front edge; the lid caps the back edge
key_z = keypad_z0 + key_zoff;
pcb_front_y = inner_h / 2 + key_wall + key_proud - switch_h;  // switch side of the PCB
pcb_back_y = pcb_front_y - keypad_pcb_t;
keypad_guide_y = pcb_back_y - fit - 1.6;                     // guides' inner face
keypad_span = keypad_w / 2 + fit + keypad_guide_w;           // half-width incl. guides

foot_slot = depth + 0.6;
foot_pivot = [foot_d * 0.55, foot_base];  // back-bottom corner of the slot (Y, Z)

echo(outer_size = [outer_w, outer_h, depth]);
// Read by enclosure/build_viewer.py.
echo(viewer = [
  ["outer", [outer_w, outer_h, depth]],
  ["stack", [face_t, panel_t, foam_t, plate_t, electronics_h, lid_t]],
  ["z", [face_t, z_plate, z_lid]],
  ["panel", [panel_w, panel_h, panel_t]],
  ["active", [active_w, active_h, window_c[0], window_c[1]]],
  ["fpc_w", fpc_w],
  ["esp32_board", esp32_board],
  ["adapter_board", adapter_board],
  ["foot", [foot_w, foot_d, foot_base, foot_slot, foot_pivot[0], foot_pivot[1], tilt]],
  ["keypad", [keypad_w, keypad_h, len(key_offsets)]]
]);
assert(post_xy[1] + post_d / 2 < inner_h / 2 - 0.5, "posts collide with the wall; widen border");
assert(norm([boss_xy[0] - post_xy[0], boss_xy[1] - post_xy[1]]) > boss_d / 2 + fit + post_d / 2,
       "plate pillars collide with the screw bosses");
assert(post_xy[0] - post_d / 2 > fpc_x + fpc_w / 2, "posts collide with the FPC gap");
assert(switch_h > key_wall + key_proud + 1, "switch too short to reach through the wall");
assert(keypad_z0 > face_t, "button module taller than the frame depth");
assert(abs(keypad_x) + keypad_span + fit < post_xy[0] - post_d / 2, "button guides collide with the plate posts");

module rounded_rect(w, h, r, t) {
  linear_extrude(t) offset(r) square([w - 2 * r, h - 2 * r], center = true);
}

module at_corners(xy) {
  for (sx = [-1, 1], sy = [-1, 1]) translate([sx * xy[0], sy * xy[1], 0]) children();
}

// A cylinder at each boss position merged into the wall corner.
module boss_shape(d, h) {
  for (sx = [-1, 1], sy = [-1, 1]) translate([sx * boss_xy[0], sy * boss_xy[1], 0]) {
    cylinder(d = d, h = h);
    translate([sx > 0 ? 0 : -d / 2, sy > 0 ? 0 : -d / 2, 0]) cube([d / 2, d / 2, h]);
  }
}

// Window through the face, with a 45° bevel opening toward the viewer. Printed
// face down, the bevel is a 45° overhang and needs no support.
module window_cut() {
  bevel = min(face_t - 0.4, 1.6);
  translate([window_c[0], window_c[1], 0]) {
    hull() {
      translate([0, 0, -0.01]) linear_extrude(0.01)
        square([window_w + 2 * bevel, window_h + 2 * bevel], center = true);
      translate([0, 0, bevel]) linear_extrude(0.01) square([window_w, window_h], center = true);
    }
    translate([0, 0, bevel - 0.01]) linear_extrude(face_t) square([window_w, window_h], center = true);
  }
}

// Grooved guides on the inside of the top wall, one at each end of the module.
module keypad_guides() {
  grip = 1.0;
  for (s = [-1, 1]) difference() {
    translate([keypad_x + (s > 0 ? keypad_w / 2 - grip : -keypad_span), keypad_guide_y, face_t])
      cube([keypad_guide_w + fit + grip, inner_h / 2 - keypad_guide_y + 0.01, z_lid - face_t]);
    translate([keypad_x + (s > 0 ? keypad_w / 2 - grip - 0.01 : -(keypad_w / 2 + fit)),
               pcb_back_y - fit, keypad_z0])
      cube([grip + fit + 0.01, keypad_pcb_t + 2 * fit, z_lid]);
  }
}

// Key holes through the top wall, in a shallow recess on the outside.
module keypad_cut() {
  xs = [for (k = key_offsets) keypad_x + k];
  translate([keypad_x - keypad_w / 2, inner_h / 2 + key_wall, key_z - key_hole_d / 2 - 3.5])
    cube([keypad_w, wall, key_hole_d + 7]);
  for (x = xs) translate([x, inner_h / 2 - 1, key_z]) rotate([-90, 0, 0])
    cylinder(d = key_hole_d, h = wall + 2);
}

module frame() {
  difference() {
    union() {
      difference() {
        rounded_rect(outer_w, outer_h, corner_r, z_lid);
        translate([0, 0, face_t]) rounded_rect(inner_w, inner_h, max(corner_r - wall, 0.5), z_lid);
      }
      boss_shape(boss_d, z_lid);
      at_corners(post_xy) cylinder(d = post_d, h = z_plate);
      keypad_guides();
      // Ridge that locates the panel, open where the flex cable leaves.
      translate([0, 0, face_t]) difference() {
        linear_extrude(panel_t + foam_t - 0.3) difference() {
          square([pocket_w + 2 * lip_t, pocket_h + 2 * lip_t], center = true);
          square([pocket_w, pocket_h], center = true);
        }
        translate([fpc_x - fpc_w / 2, -pocket_h / 2 - lip_t - 1, -1]) cube([fpc_w, lip_t + 2, 10]);
      }
    }
    window_cut();
    keypad_cut();
    at_corners(boss_xy) translate([0, 0, z_lid - pilot_depth]) cylinder(d = pilot_d, h = pilot_depth + 1);
  }
}

// Two grooved rails along a board's long edges and a stop at the +X end.
module board_rails(b) {
  l = b[0]; w = b[1]; t = b[2]; lift = b[3];
  grip = 1.0;   // how far the PCB edge sits in the groove
  side = 1.6;   // rail wall outside the groove
  top = 1.2;    // lip above the PCB
  groove_z = plate_t + lift;
  h = groove_z + t + fit + top;
  translate([b[4], b[5], 0]) rotate(b[6]) {
    for (s = [-1, 1]) difference() {
      translate([-l / 2, s > 0 ? w / 2 - grip : -(w / 2 + fit + side), 0])
        cube([l, grip + fit + side, h]);
      translate([-l / 2 - 1, s > 0 ? w / 2 - grip - 0.01 : -(w / 2 + fit), groove_z])
        cube([l + 2, grip + fit + 0.01, t + fit]);
    }
    translate([l / 2 + fit, -(w / 2 + fit + side), 0])
      cube([side, w + 2 * (fit + side), groove_z + t]);
  }
}

module plate() {
  pw = inner_w - 2 * fit;
  ph = inner_h - 2 * fit;
  difference() {
    union() {
      rounded_rect(pw, ph, 1, plate_t);
      // Pillars over the posts; the lid presses them to clamp the panel.
      at_corners(post_xy) cylinder(d = post_d, h = plate_t + electronics_h - fit);
      board_rails(esp32_board);
      board_rails(adapter_board);
    }
    translate([0, 0, -1]) boss_shape(boss_d + 2 * fit, plate_t + electronics_h + 2);
    // Clearance for the button module's guides.
    translate([keypad_x - keypad_span - fit, keypad_guide_y - fit, -1])
      cube([2 * (keypad_span + fit), ph / 2 - keypad_guide_y + fit + 1, plate_t + 2]);
    // Opening for the flex cable, from the bottom edge to behind the panel.
    translate([fpc_x - (fpc_w + 2) / 2, -ph / 2 - 1, -1])
      cube([fpc_w + 2, (ph - pocket_h) / 2 + 1 + fpc_reach, plate_t + 2]);
  }
}

module keyhole() {
  cylinder(d = 8, h = lid_t + 2);
  hull() {
    cylinder(d = 4, h = lid_t + 2);
    translate([0, 8, 0]) cylinder(d = 4, h = lid_t + 2);
  }
}

// Modeled with the inner side at Z = 0; print it as modeled (outer side up).
module lid() {
  difference() {
    rounded_rect(outer_w, outer_h, corner_r, lid_t);
    at_corners(boss_xy) {
      translate([0, 0, -1]) cylinder(d = screw_d, h = lid_t + 2);
      translate([0, 0, lid_t - screw_head_t]) cylinder(d = screw_head_d, h = lid_t);
    }
    translate([cable_x - cable_w / 2, -outer_h / 2 - 1, -1]) cube([cable_w, wall + 5, lid_t + 2]);
    for (sx = [-1, 1]) translate([sx * keyhole_dx, outer_h / 2 - 25, -1]) keyhole();
  }
}

// Desk stand; print two. The frame's bottom edge sits in the slot, leaning
// back by `tilt`.
module foot() {
  fw = foot_w; fd = foot_d; base_t = foot_base;
  slot = foot_slot;
  front = 3; back = 4; hold = 14;
  pivot = [0, foot_pivot[0], foot_pivot[1]];
  intersection() {
    difference() {
      hull() {
        cube([fw, fd, base_t]);
        translate(pivot) rotate([-tilt, 0, 0])
          translate([0, -(front + slot), -base_t]) cube([fw, front + slot + back, hold + base_t]);
      }
      translate(pivot) rotate([-tilt, 0, 0]) translate([-1, -slot, 0]) cube([fw + 2, slot, hold + 40]);
    }
    translate([-1, -1, 0]) cube([fw + 2, fd + 2, 100]);
  }
}

// Stand-ins for previews; not printed.
module panel_dummy() {
  translate([-panel_w / 2, -panel_h / 2, face_t]) cube([panel_w, panel_h, panel_t]);
}

// PCB outlines at their place in the rails (plate coordinates).
module board_dummies() {
  for (b = [esp32_board, adapter_board])
    translate([b[4], b[5], plate_t + b[3]]) rotate(b[6]) translate([-b[0] / 2, -b[1] / 2, 0])
      cube([b[0], b[1], b[2]]);
}

// Button module stand-in, in frame coordinates.
module keypad_dummy() {
  translate([keypad_x - keypad_w / 2, pcb_back_y, keypad_z0]) cube([keypad_w, keypad_pcb_t, keypad_h]);
  for (k = key_offsets) translate([keypad_x + k, pcb_front_y, key_z]) {
    translate([-3, 0, -3]) cube([6, 3.5, 6]);
    rotate([-90, 0, 0]) cylinder(d = 3.5, h = switch_h);
  }
}

module assembly(gap) {
  color("#333") frame();
  color("#a33") keypad_dummy();
  color("white") translate([0, 0, gap]) panel_dummy();
  translate([0, 0, z_plate + 2 * gap]) {
    color("#c96") plate();
    color("#a33") board_dummies();
  }
  color("#555", 0.8) translate([0, 0, z_lid + 3 * gap]) lid();
}

module place(z) {
  if (placed) translate([0, 0, z]) children();
  else children();
}

if (part == "frame") frame();
else if (part == "plate") place(z_plate) plate();
else if (part == "lid") place(z_lid) lid();
else if (part == "foot") foot();
else if (part == "panel") panel_dummy();
else if (part == "boards") place(z_plate) board_dummies();
else if (part == "keypad") keypad_dummy();
else assembly(part == "exploded" ? 25 : 0);
