"""
	Flowblade Movie Editor is a nonlinear video editor.
    Copyright 2012 Janne Liljeblad.

	This file is part of Flowblade Movie Editor <http://code.google.com/p/flowblade>.

	Flowblade Movie Editor is free software: you can redistribute it and/or modify
	it under the terms of the GNU General Public License as published by
	the Free Software Foundation, either version 3 of the License, or
	(at your option) any later version.

	Flowblade Movie Editor is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.

	You should have received a copy of the GNU General Public License
	along with Flowblade Movie Editor.  If not, see <http://www.gnu.org/licenses/>.
"""

"""
Module contains GUI widgets used to edit keyframed properties in filters and
compositors.

NOTE: All the editors are composites of smaller objects (so that similar 
but slighly different editors can be made in the future). There are a lots 
of callbacks to parent objects, and the naming of the classes isn't probably 
very good, so this may not be as readable code as it perhaps could be.
"""
import cairo
import copy
import gtk
import math
import pango

from cairoarea import CairoDrawableArea
import appconsts
from editorstate import PLAYER
from editorstate import current_sequence
import gui
import guiutils
import propertyedit
import propertyparse
import respaths
import updater
import utils

# Draw consts
CLIP_EDITOR_WIDTH = 250 
CLIP_EDITOR_HEIGHT = 21
END_PAD = 18
TOP_PAD = 2
BUTTON_WIDTH = 26
BUTTON_HEIGHT = 24
KF_Y = 5
CENTER_LINE_Y = 11
POS_ENTRY_W = 38
POS_ENTRY_H = 20
KF_HIT_WIDTH = 4
KF_DRAG_THRESHOLD = 3
EP_HALF = 4

GEOMETRY_EDITOR_WIDTH = 250
GEOMETRY_EDITOR_HEIGHT = 200
GEOM_EDITOR_SIZE_LARGE = 0.9
GEOM_EDITOR_SIZE_SMALL = 0.3
GEOM_EDITOR_SIZE_MEDIUM = 0.6 # screensize as fraction of available height
GEOM_EDITOR_SIZES = [GEOM_EDITOR_SIZE_LARGE, GEOM_EDITOR_SIZE_MEDIUM, GEOM_EDITOR_SIZE_SMALL]

# rectangle edit handles ids. Points numbered in clockwise direction to get opposite points easily.
TOP_LEFT = 0
TOP_MIDDLE = 1
TOP_RIGHT = 2
MIDDLE_RIGHT = 3
BOTTOM_RIGHT = 4
BOTTOM_MIDDLE = 5
BOTTOM_LEFT = 6
MIDDLE_LEFT = 7

# hit values for rect, edit point hits return edit point id
AREA_HIT = 9
NO_HIT = 10

# Colors
POINTER_COLOR = (1, 0.3, 0.3)
CLIP_EDITOR_BG_COLOR = (0.7, 0.7, 0.7)
LIGHT_MULTILPLIER = 1.14
DARK_MULTIPLIER = 0.74
EDITABLE_RECT_COLOR = (0,0,0.7)
NOT_EDITABLE_RECT_COLOR = (1,0,0)

# Editor states
KF_DRAG = 0
POSITION_DRAG = 1
KF_DRAG_DISABLED = 2

# Icons
ACTIVE_KF_ICON = None
NON_ACTIVE_KF_ICON = None

# magic value to signify disconnected signal handler 
DISCONNECTED_SIGNAL_HANDLER = -9999999

# ----------------------------------------------------- editor objects
class ClipKeyFrameEditor:
    """
    GUI component used to add, move and remove keyframes 
    inside a single clip. It is used as a component inside a parent editor and
    needs the parent editor to write out keyframe values.
    
    Parent editor must implement callback interface:
        def clip_editor_frame_changed(self, frame)
        def active_keyframe_changed(self)
        def keyframe_dragged(self, active_kf, frame)
        def update_slider_value_display(self, frame)
    """

    def __init__(self, editable_property, parent_editor, use_clip_in=True):
        self.widget = CairoDrawableArea(CLIP_EDITOR_WIDTH, 
                                        CLIP_EDITOR_HEIGHT, 
                                        self._draw)
        self.widget.press_func = self._press_event
        self.widget.motion_notify_func = self._motion_notify_event
        self.widget.release_func = self._release_event

        self.clip_length = editable_property.get_clip_length() - 1 # -1 added to get correct results, yeah...
        
        # Some filters start keyframes from *MEDIA* frame 0
        # Some filters or compositors start keyframes from *CLIP* frame 0
        # Filters starting from *MEDIA* 0 need offset to clip start added to all values.
        self.use_clip_in = use_clip_in
        if self.use_clip_in == True:
            self.clip_in = editable_property.clip.clip_in
        else:
            self.clip_in = 0
        self.current_clip_frame = self.clip_in

        self.keyframes = [(0, 0.0)]
        self.active_kf_index = 0

        self.parent_editor = parent_editor

        self.keyframe_parser = None # Function used to parse keyframes to tuples is different for different expressions
                                    # Parent editor sets this.
                                    
        self.current_mouse_action = None
        self.drag_on = False # Used to stop updating pos here if pos change is initiated here.
        self.drag_min = -1
        self.drag_max = -1
        
        # init icons if needed
        global ACTIVE_KF_ICON, NON_ACTIVE_KF_ICON
        if ACTIVE_KF_ICON == None:
            ACTIVE_KF_ICON = gtk.gdk.pixbuf_new_from_file(respaths.IMAGE_PATH + "kf_active.png")
        if NON_ACTIVE_KF_ICON == None:
            NON_ACTIVE_KF_ICON = gtk.gdk.pixbuf_new_from_file(respaths.IMAGE_PATH + "kf_not_active.png")    
            
    def set_keyframes(self, keyframes_str, out_to_in_func):
        self.keyframes = self.keyframe_parser(keyframes_str, out_to_in_func)
        
    def _get_panel_pos(self):
        return self._get_panel_pos_for_frame(self.current_clip_frame) 

    def _get_panel_pos_for_frame(self, frame):
        active_width = self.widget.allocation.width - 2 * END_PAD
        disp_frame = frame - self.clip_in 
        return END_PAD + int((float(disp_frame) / float(self.clip_length)) * 
                             active_width)

    def _get_frame_for_panel_pos(self, panel_x):
        active_width = self.widget.allocation.width - 2 * END_PAD
        clip_panel_x = panel_x - END_PAD
        norm_pos = float(clip_panel_x) / float(active_width)
        return int(norm_pos * self.clip_length) + self.clip_in
        
    def _set_clip_frame(self, panel_x):
        self.current_clip_frame = self._get_frame_for_panel_pos(panel_x)
    
    def move_clip_frame(self, delta):
        self.current_clip_frame = self.current_clip_frame + delta
        self._force_current_in_frame_range()

    def set_and_display_clip_frame(self, clip_frame):
        self.current_clip_frame = clip_frame
        self._force_current_in_frame_range()

    def _draw(self, event, cr, allocation):
        """
        Callback for repaint from CairoDrawableArea.
        We get cairo context and allocation.
        """
        x, y, w, h = allocation
        active_width = w - 2 * END_PAD
        active_height = h - 2 * TOP_PAD      
        
        # Draw bg
        cr.set_source_rgb(*(gui.bg_color_tuple))
        cr.rectangle(0, 0, w, h)
        cr.fill()
        
        # Draw clip bg  
        cr.set_source_rgb(*CLIP_EDITOR_BG_COLOR)
        cr.rectangle(END_PAD, TOP_PAD, active_width, active_height)
        cr.fill()

        # Clip edge and emboss
        rect = (END_PAD, TOP_PAD, active_width, active_height)
        self.draw_edge(cr, rect)
        self.draw_emboss(cr, rect, gui.bg_color_tuple)

        # Draw center line
        cr.set_source_rgb(0.4, 0.4, 0.4)
        cr.set_line_width(2.0)
        cr.move_to(END_PAD, CENTER_LINE_Y)
        cr.line_to(END_PAD + active_width, CENTER_LINE_Y)
        cr.stroke()

        # Draw keyframes
        for i in range(0, len(self.keyframes)):
            frame, value = self.keyframes[i]            
            if i == self.active_kf_index:
                icon = ACTIVE_KF_ICON
            else:
                icon = NON_ACTIVE_KF_ICON
            try:
                kf_pos = self._get_panel_pos_for_frame(frame)
            except ZeroDivisionError: # math fails for 1 frame long clip
                kf_pos = END_PAD
            cr.set_source_pixbuf(icon, kf_pos - 6, KF_Y)
            cr.paint()

        # Draw frame pointer
        try:
            panel_pos = self._get_panel_pos()
        except ZeroDivisionError: # math fails for 1 frame long clip
            panel_pos = END_PAD
        cr.set_line_width(2.0)
        cr.set_source_rgb(*POINTER_COLOR)
        cr.move_to(panel_pos, 0)
        cr.line_to(panel_pos, CLIP_EDITOR_HEIGHT)
        cr.stroke()
        
    def draw_emboss(self, cr, rect, color):
        # Emboss, corner points
        left = rect[0] + 1.5
        up = rect[1] + 1.5
        right = left + rect[2] - 2.0
        down = up + rect[3] - 2.0
            
        # Draw lines
        light_color = guiutils.get_multiplied_color(color, LIGHT_MULTILPLIER)
        cr.set_source_rgb(*light_color)
        cr.move_to(left, down)
        cr.line_to(left, up)
        cr.stroke()
            
        cr.move_to(left, up)
        cr.line_to(right, up)
        cr.stroke()

        dark_color = guiutils.get_multiplied_color(color, DARK_MULTIPLIER)
        cr.set_source_rgb(*dark_color)
        cr.move_to(right, up)
        cr.line_to(right, down)
        cr.stroke()
            
        cr.move_to(right, down)
        cr.line_to(left, down)
        cr.stroke()

    def draw_edge(self, cr, rect):
        cr.set_line_width(1.0)
        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(rect[0] + 0.5, rect[1] + 0.5, rect[2], rect[3])
        cr.stroke()

    def _press_event(self, event):
        """
        Mouse button callback
        """
        self.drag_on = True

        lx = self._legalize_x(event.x)
        hit_kf = self._key_frame_hit(lx, event.y)

        if hit_kf == None: # nothing was hit
            self.current_mouse_action = POSITION_DRAG
            self._set_clip_frame(lx)
            self.parent_editor.clip_editor_frame_changed(self.current_clip_frame)
            self.widget.queue_draw()
        else: # some keyframe was pressed
            self.active_kf_index = hit_kf
            frame, value = self.keyframes[hit_kf]
            self.current_clip_frame = frame
            self.parent_editor.active_keyframe_changed()
            if hit_kf == 0:
                self.current_mouse_action = KF_DRAG_DISABLED
            else:
                self.current_mouse_action = KF_DRAG
                
                self.drag_start_x = event.x
                
                prev_frame, val = self.keyframes[hit_kf - 1]
                self.drag_min = prev_frame  + 1
                try:
                    next_frame, val = self.keyframes[hit_kf + 1]
                    self.drag_max = next_frame - 1
                except:
                    self.drag_max = self.clip_length - 1
            self.widget.queue_draw()

    def _motion_notify_event(self, x, y, state):
        """
        Mouse move callback
        """
        lx = self._legalize_x(x)
        
        if self.current_mouse_action == POSITION_DRAG:
            self._set_clip_frame(lx)
            self.parent_editor.clip_editor_frame_changed(self.current_clip_frame)
        elif self.current_mouse_action == KF_DRAG:
            if abs(lx - self.drag_start_x) < KF_DRAG_THRESHOLD:
                return
            
            frame = self._get_drag_frame(lx)
            self.set_active_kf_frame(frame)
            self.current_clip_frame = frame
            self.parent_editor.keyframe_dragged(self.active_kf_index, frame)
            self.parent_editor.active_keyframe_changed()

        self.widget.queue_draw()
        
    def _release_event(self, event):
        """
        Mouse release callback.
        """
        lx = self._legalize_x(event.x)

        if self.current_mouse_action == POSITION_DRAG:
            self._set_clip_frame(lx)
            self.parent_editor.clip_editor_frame_changed(self.current_clip_frame)
            self.parent_editor.update_slider_value_display(self.current_clip_frame)
        elif self.current_mouse_action == KF_DRAG:
            if abs(lx - self.drag_start_x) < KF_DRAG_THRESHOLD:
                return
            frame = self._get_drag_frame(lx)
            self.set_active_kf_frame(frame)
            self.current_clip_frame = frame
            self.parent_editor.keyframe_dragged(self.active_kf_index, frame)
            self.parent_editor.active_keyframe_changed()
            self.parent_editor.update_property_value()
            self.parent_editor.update_slider_value_display(frame)   

        self.widget.queue_draw()
        self.current_mouse_action = None
        
        self.drag_on = False
        
    def _legalize_x(self, x):
        """
        Get x in pixel range between end pads.
        """
        w = self.widget.allocation.width
        if x < END_PAD:
            return END_PAD
        elif x > w - END_PAD:
            return w - END_PAD
        else:
            return x
    
    def _force_current_in_frame_range(self):
        if self.current_clip_frame < self.clip_in:
            self.current_clip_frame = self.clip_in
        if self.current_clip_frame > self.clip_in + self.clip_length:
            self.current_clip_frame = self.clip_in + self.clip_length
            
    def _get_drag_frame(self, panel_x):
        """
        Get x in range available for current drag.
        """
        frame = self._get_frame_for_panel_pos(panel_x)
        if frame < self.drag_min:
            frame = self.drag_min
        if frame > self.drag_max:
            frame = self.drag_max
        return frame
    
    def _key_frame_hit(self, x, y):
        for i in range(0, len(self.keyframes)):
            frame, val = self.keyframes[i]
            frame_x = self._get_panel_pos_for_frame(frame)
            frame_y = KF_Y + 6
            if((abs(x - frame_x) < KF_HIT_WIDTH)
                and (abs(y - frame_y) < KF_HIT_WIDTH)):
                return i
            
        return None
        
    def add_keyframe(self, frame):
        kf_index_on_frame = self.frame_has_keyframe(frame)
        if kf_index_on_frame != -1:
            # Trying add on top of existing keyframe makes it active
            self.active_kf_index = kf_index_on_frame
            return

        for i in range(0, len(self.keyframes)):
            kf_frame, kf_value = self.keyframes[i]
            if kf_frame > frame:
                prev_frame, prev_value = self.keyframes[i - 1]
                self.keyframes.insert(i, (frame, prev_value))
                self.active_kf_index = i
                return
        prev_frame, prev_value = self.keyframes[len(self.keyframes) - 1]
        self.keyframes.append((frame, prev_value))
        self.active_kf_index = len(self.keyframes) - 1

    def print_keyframes(self):
        print "clip edit keyframes:"
        for i in range(0, len(self.keyframes)):
            print self.keyframes[i]
        
    def delete_active_keyframe(self):
        if self.active_kf_index == 0:
            # keyframe frame 0 cannot be removed
            return
        self.keyframes.pop(self.active_kf_index)
        self.active_kf_index -= 1
        if self.active_kf_index < 0:
            self.active_kf_index = 0
        self._set_pos_to_active_kf()

    def set_next_active(self):
        """
        Activates next keyframe or keeps last active to stay in range.
        """
        self.active_kf_index += 1
        if self.active_kf_index > (len(self.keyframes) - 1):
            self.active_kf_index = len(self.keyframes) - 1
        self._set_pos_to_active_kf()
        
    def set_prev_active(self):
        """
        Activates previous keyframe or keeps first active to stay in range.
        """
        self.active_kf_index -= 1
        if self.active_kf_index < 0:
            self.active_kf_index = 0
        self._set_pos_to_active_kf()
    
    def _set_pos_to_active_kf(self):
        frame, value = self.keyframes[self.active_kf_index]
        self.current_clip_frame = frame
        self._force_current_in_frame_range()
        self.parent_editor.update_slider_value_display(self.current_clip_frame)   
            
    def frame_has_keyframe(self, frame):
        """
        Returns index of keyframe if frame has keyframe or -1 if it doesn't.
        """
        for i in range(0, len(self.keyframes)):
            kf_frame, kf_value = self.keyframes[i]
            if frame == kf_frame:
                return i

        return -1
    
    def get_active_kf_frame(self):
        frame, val = self.keyframes[self.active_kf_index]
        return frame

    def get_active_kf_value(self):
        frame, val = self.keyframes[self.active_kf_index]
        return val
    
    def set_active_kf_value(self, new_value):
        frame, val = self.keyframes.pop(self.active_kf_index)
        self.keyframes.insert(self.active_kf_index,(frame, new_value))

    def active_kf_pos_entered(self, frame):
        if self.active_kf_index == 0:
            return
        
        prev_frame, val = self.keyframes[self.active_kf_index - 1]
        prev_frame += 1
        try:
            next_frame, val = self.keyframes[self.active_kf_index + 1]
            next_frame -= 1
        except:
            next_frame = self.clip_length - 1
        
        frame = max(frame, prev_frame)
        frame = min(frame, next_frame)

        self.set_active_kf_frame(frame)
        self.current_clip_frame = frame    
        
    def set_active_kf_frame(self, new_frame):
        frame, val = self.keyframes.pop(self.active_kf_index)
        self.keyframes.insert(self.active_kf_index,(new_frame, val))

class EditRect:
    """
    Line box with corner and middle handles that user can use to set
    position, width and height of rectangle geometry.
    """
    def __init__(self, x, y, w, h):
        self.editable = True
        self.edit_points = {}
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.start_x = None
        self.start_y = None
        self.start_w = None
        self.start_h = None
        self.start_op_x = None
        self.start_op_y = None
        self.projection_point = None
        self.set_edit_points()
        
    def set_geom(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.set_edit_points()
        
    def set_edit_points(self):
        self.edit_points[TOP_LEFT] = (self.x, self.y)
        self.edit_points[TOP_MIDDLE] = (self.x + self.w/2, self.y)
        self.edit_points[TOP_RIGHT] = (self.x + self.w, self.y)
        self.edit_points[MIDDLE_LEFT] = (self.x, self.y + self.h/2)
        self.edit_points[MIDDLE_RIGHT] = (self.x + self.w, self.y + self.h/2)
        self.edit_points[BOTTOM_LEFT] = (self.x, self.y + self.h)
        self.edit_points[BOTTOM_MIDDLE] = (self.x + self.w/2, self.y + self.h)
        self.edit_points[BOTTOM_RIGHT] = (self.x + self.w, self.y + self.h)
        
    def check_hit(self, x, y):
        for id_int, value in self.edit_points.iteritems():
            x1, y1 = value
            if (x >= x1 - EP_HALF and x <= x1 + EP_HALF and y >= y1 - EP_HALF and y <= y1 + EP_HALF):
                return id_int
            
        x1, y1 = self.edit_points[TOP_LEFT]     
        x2, y2 = self.edit_points[BOTTOM_RIGHT]
        
        if (x >= x1 and x <= x2 and y >= y1 and y <= y2):
            return AREA_HIT
            
        return NO_HIT
    
    def edit_point_drag_started(self, ep_id):
        opposite_id = (ep_id + 4) % 8
        
        self.drag_ep = ep_id
        self.guide_line = utils.get_line_for_points(self.edit_points[ep_id],
                                                    self.edit_points[opposite_id])
        x, y = self.edit_points[ep_id]
        self.start_x = x
        self.start_y = y
        opx, opy = self.edit_points[opposite_id]
        self.start_op_x = opx
        self.start_op_y = opy
        self.start_w = self.w
        self.start_h = self.h
    
        self.projection_point = (x, y)
    
    def edit_point_drag(self, delta_x, delta_y):
        x = self.start_x + delta_x
        y = self.start_y + delta_y

        p = (x, y)
        lx, ly = self.guide_line.get_normal_projection_point(p)
        self.projection_point = (lx, ly)

        # Set new rect
        if self.drag_ep == TOP_LEFT:
            self.x = lx
            self.y = ly
            self.w = self.start_op_x - lx
            self.h = self.start_op_y - ly
        elif self.drag_ep == BOTTOM_RIGHT:
            self.x = self.start_op_x
            self.y = self.start_op_y
            self.w = lx - self.start_op_x
            self.h = ly - self.start_op_y
        elif self.drag_ep == BOTTOM_LEFT:
            self.x = lx
            self.y = self.start_op_y
            self.w = self.start_op_x - lx
            self.h = ly - self.start_op_y
        elif self.drag_ep == TOP_RIGHT:
            self.x = self.start_op_x
            self.y = ly
            self.w = lx - self.start_op_x
            self.h = self.start_op_y - ly
        elif self.drag_ep == MIDDLE_RIGHT:
            self.x = self.start_op_x
            self.y = self.start_op_y - (self.start_h / 2.0)
            self.w = lx - self.start_op_x
            self.h = self.start_h
        elif self.drag_ep == MIDDLE_LEFT:
            self.x = lx
            self.y = self.start_y - (self.start_h / 2.0)
            self.w = self.start_op_x - lx
            self.h = self.start_h
        elif self.drag_ep == TOP_MIDDLE:
            self.x = self.start_x - (self.start_w / 2.0)
            self.y = ly
            self.w = self.start_w
            self.h = self.start_op_y - ly
        elif self.drag_ep == BOTTOM_MIDDLE:
            self.x = self.start_op_x - (self.start_w / 2.0)
            self.y = self.start_op_y
            self.w = self.start_w
            self.h = ly - self.start_op_y
        
        # No negative size
        if self.w < 1.0:
            self.w = 1.0
        if self.h < 1.0:
            self.h = 1.0

        self.set_edit_points()
    
    def clear_projection_point(self):
        self.projection_point = None
    
    def move_started(self):
        self.start_x = self.x
        self.start_y = self.y
    
    def move_drag(self, delta_x, delta_y):
        self.x = self.start_x + delta_x
        self.y = self.start_y + delta_y

        self.set_edit_points()
        
    def draw(self, cr):
        # Box
        cr.set_line_width(1.0)
        color = EDITABLE_RECT_COLOR
        cr.set_source_rgb(*color)
        cr.rectangle(self.x + 0.5, self.y + 0.5, self.w, self.h)
        cr.stroke()

        # handles
        for id_int, pos in self.edit_points.iteritems():
            x, y = pos
            cr.rectangle(x - 2, y - 2, 4, 4)
            cr.fill()
        
        if self.projection_point != None:
            x, y = self.projection_point
            cr.set_source_rgb(0,1,0)
            cr.rectangle(x - 2, y - 2, 4, 4)
            cr.fill()
        
def _geom_kf_sort(kf):
    """
    Function is used to sort keyframes by frame number.
    """
    frame, rect, opacity = kf
    return frame 
        
class GeometryKeyFrameEditor:
    """
    GUI component for editing position and scale values of keyframes 
    of source image in compositors. 
    
    Component is used as a part of e.g GeometryEditor, which handles
    also keyframe creation and deletion and opacity, and
    writing out the keyframes with combined information.
    """
    def __init__(self, editable_property, parent_editor):
        self.widget = CairoDrawableArea(GEOMETRY_EDITOR_WIDTH, 
                                        GEOMETRY_EDITOR_HEIGHT, 
                                        self._draw)
        """
        Needed parent_editor callback interface:
            def geometry_edit_started(self)
            def geometry_edit_finished(sel)
            def update_request_from_geom_editor(self)
        """
        self.widget.press_func = self._press_event
        self.widget.motion_notify_func = self._motion_notify_event
        self.widget.release_func = self._release_event

        self.clip_length = editable_property.get_clip_length()
        self.pixel_aspect_ratio = editable_property.get_pixel_aspect_ratio()
        self.current_clip_frame = 0
        self.source_edit_rect = None # Created later when we have allocation available
        
        # Keyframe tuples are of type (frame, rect, opacity)
        self.keyframes = None # Set using set_keyframes()
        self.keyframe_parser = None # Function used to parse keyframes to tuples is different for different expressions
                                    # Parent editor sets this.
            
        self.current_mouse_hit = None
        self.start_x = None
        self.start_Y = None

        self.parent_editor = parent_editor
        
        self.source_width = -1 # unscaled source image width, set later
        self.source_height = -1 # unscaled source image height, set later
        
        self.coords = None # Calculated later when we have allocation available
        
    def init_editor(self, source_width, source_height, y_fract):
        self.source_width = source_width 
        self.source_height = source_height
        self.y_fract = y_fract
        self.screen_ratio = float(source_width) / float(source_height)
    
    def set_view_size(self, y_fract):
        self.y_fract = y_fract
        self._create_coords()

    def set_keyframes(self, keyframes_str, out_to_in_func):
        self.keyframes = self.keyframe_parser(keyframes_str, out_to_in_func)
    
    def set_keyframe_frame(self, active_kf_index, frame):
        old_frame, rect, opacity = self.keyframes[active_kf_index]
        self.keyframes.pop(active_kf_index)
        self.keyframes.insert(active_kf_index, (frame, rect, opacity))        

    def reset_active_keyframe_rect(self, active_kf_index):
        frame, old_rect, opacity = self.keyframes[active_kf_index]
        rect = [0, 0, self.source_width, self.source_height]
        self.keyframes.pop(active_kf_index)
        self.keyframes.insert(active_kf_index, (frame, rect, opacity))     

    def reset_active_keyframe_rect_ratio(self, active_kf_index):
        frame, old_rect, opacity = self.keyframes[active_kf_index]
        x, y, w, h = old_rect
        new_h = int(float(w) * (float(self.source_height) / float(self.source_width)))
        rect = [x, y, w, new_h]
        self.keyframes.pop(active_kf_index)
        self.keyframes.insert(active_kf_index, (frame, rect, opacity))   

    def add_keyframe(self, frame):
        if self._frame_has_keyframe(frame) == True:
            return

        # Get previous keyframe
        prev_kf = None
        for i in range(0, len(self.keyframes)):
            p_frame, p_rect, p_opacity = self.keyframes[i]
            if p_frame < frame:
                prev_kf = self.keyframes[i]                
        if prev_kf == None:
            prev_kf = self.keyframes[len(self.keyframes) - 1]
        
        # Add with values of previous
        p_frame, p_rect, p_opacity = prev_kf
        self.keyframes.append((frame, copy.deepcopy(p_rect), copy.deepcopy(p_opacity)))
        
        self.keyframes.sort(key=_geom_kf_sort)
    
    def delete_active_keyframe(self, keyframe_index):
        #print keyframe_index
        if keyframe_index == 0:
            # keyframe frame 0 cannot be removed
            return
        self.keyframes.pop(keyframe_index)

    def _frame_has_keyframe(self, frame):
        for i in range(0, len(self.keyframes)):
            kf = self.keyframes[i]
            kf_frame, rect, opacity = kf
            if frame == kf_frame:
                return True

        return False
        
    def set_clip_frame(self, frame):
        self.current_clip_frame = frame
        if self.source_edit_rect != None:
            self._update_source_rect()
            
    def set_keyframe_to_edit_rect(self, kf_index):
        value_rect = self._get_source_edit_rect_to_screen_rect()
        frame, rect, opacity = self.keyframes[kf_index]
        self.keyframes.pop(kf_index)
        new_kf = (frame, value_rect, opacity)
        self.keyframes.append(new_kf)
        
        self.keyframes.sort(key=_geom_kf_sort)
        
        self._update_source_rect()

    def _update_source_rect(self):
        for i in range(0, len(self.keyframes)):
            frame, rect, opacity = self.keyframes[i]
            if frame == self.current_clip_frame:
                self.source_edit_rect.set_geom(*self._get_screen_to_panel_rect(rect))
                self.source_edit_rect.editable = True
                return
            
            try:
                # See if frame between this and next keyframe
                frame_n, rect_n, opacity_n = self.keyframes[i + 1]
                if ((frame < self.current_clip_frame)
                    and (self.current_clip_frame < frame_n)):
                    time_fract = float((self.current_clip_frame - frame)) / \
                                 float((frame_n - frame))
                    frame_rect = self._get_interpolated_rect(rect, rect_n, time_fract)
                    self.source_edit_rect.set_geom(*self._get_screen_to_panel_rect(frame_rect))
                    self.source_edit_rect.editable = False
                    return
            except: # past last frame, use its value
                self.source_edit_rect.set_geom(*self._get_screen_to_panel_rect(rect))
                self.source_edit_rect.editable = False
                return
                
        print "reached end of _update_source_rect, this should be unreachable"
        
    def _get_interpolated_rect(self, rect_1, rect_2, fract):
        x1, y1, w1, h1 = rect_1
        x2, y2, w2, h2 = rect_2
        x = x1 + (x2 - x1) * fract
        y = y1 + (y2 - y1) * fract
        w = w1 + (w2 - w1) * fract
        h = h1 + (h2 - h1) * fract
        return (x, y, w, h)
        
    def _get_screen_to_panel_rect(self, rect):
        x, y, w, h = rect
        px = self.coords.orig_x + x / self.coords.x_scale
        py = self.coords.orig_y + y / self.coords.y_scale
        pw = w / self.coords.x_scale # scale is panel to screen, this is screen to panel
        ph = h / self.coords.y_scale # scale is panel to screen, this is screen to panel
        return (px, py, pw, ph)
    
    def _get_source_edit_rect_to_screen_rect(self):
        p_x_from_origo = self.source_edit_rect.x - self.coords.orig_x
        p_y_from_origo = self.source_edit_rect.y - self.coords.orig_y
        
        screen_x = p_x_from_origo * self.coords.x_scale
        screen_y = p_y_from_origo * self.coords.y_scale
        screen_w = self.source_edit_rect.w * self.coords.x_scale
        screen_h = self.source_edit_rect.h * self.coords.y_scale
        
        return [screen_x, screen_y, screen_w, screen_h]
        
    def _create_coords(self):
        self.coords = utils.EmptyClass()
        panel_w = self.widget.allocation.width
        panel_h = self.widget.allocation.height
        self.coords.screen_h = panel_h * self.y_fract
        self.coords.screen_w = self.coords.screen_h * self.screen_ratio * self.pixel_aspect_ratio
        self.coords.orig_x = (panel_w - self.coords.screen_w) / 2.0
        self.coords.orig_y = (panel_h - self.coords.screen_h) / 2.0
        self.coords.x_scale = self.source_width / self.coords.screen_w
        self.coords.y_scale = self.source_height / self.coords.screen_h
        
    def _draw(self, event, cr, allocation):
        """
        Callback for repaint from CairoDrawableArea.
        We get cairo contect and allocation.
        """
        if self.coords == None:
            self._create_coords()
        
        x, y, w, h = allocation
        
        # Draw bg
        cr.set_source_rgb(*(gui.bg_color_tuple))
        cr.rectangle(0, 0, w, h)
        cr.fill()
        
        # Draw screen
        cr.set_source_rgb(0.6, 0.6, 0.6)
        cr.rectangle(self.coords.orig_x, self.coords.orig_y, 
                       self.coords.screen_w, self.coords.screen_h)
        cr.fill()

        screen_rect = [self.coords.orig_x, self.coords.orig_y, 
                       self.coords.screen_w, self.coords.screen_h]
        self._draw_edge(cr, screen_rect)
        
        # Edit rect is created here only when we're sure to have allocation
        if self.source_edit_rect == None:
            self.source_edit_rect = EditRect(10, 10, 10, 10) # values are immediatyly overwritten
            self._update_source_rect()

        # Draw source
        self.source_edit_rect.draw(cr)

    def _draw_edge(self, cr, rect):
        cr.set_line_width(1.0)
        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(rect[0] + 0.5, rect[1] + 0.5, rect[2], rect[3])
        cr.stroke()
        
    def _press_event(self, event):
        """
        Mouse button callback
        """
        self.current_mouse_hit = self.source_edit_rect.check_hit(event.x, event.y)
        if self.current_mouse_hit == NO_HIT:
            return
        
        self.mouse_start_x = event.x
        self.mouse_start_y = event.y

        if self.current_mouse_hit == AREA_HIT:
            self.source_edit_rect.move_started()
        else:
            self.source_edit_rect.edit_point_drag_started(self.current_mouse_hit)

        self.parent_editor.geometry_edit_started()
        self.parent_editor.update_request_from_geom_editor()

    def _motion_notify_event(self, x, y, state):
        """
        Mouse move callback
        """
        if self.current_mouse_hit == NO_HIT:
            return
        
        delta_x = x - self.mouse_start_x
        delta_y = y - self.mouse_start_y
        
        if self.current_mouse_hit == AREA_HIT:
            self.source_edit_rect.move_drag(delta_x, delta_y)
        else:
            self.source_edit_rect.edit_point_drag(delta_x, delta_y)

        self.parent_editor.queue_draw()
        
    def _release_event(self, event):
        """
        Mouse release callback.
        """
        if self.current_mouse_hit == NO_HIT:
            return
            
        delta_x = event.x - self.mouse_start_x
        delta_y = event.y - self.mouse_start_y
        
        if self.current_mouse_hit == AREA_HIT:
            self.source_edit_rect.move_drag(delta_x, delta_y)
        else:
            self.source_edit_rect.edit_point_drag(delta_x, delta_y)
            self.source_edit_rect.clear_projection_point()
            
        self.parent_editor.geometry_edit_finished()
    
    def print_keyframes(self):
        print "geom edit keyframes:"
        for i in range(0, len(self.keyframes)):
            print self.keyframes[i]

class ClipEditorButtonsRow(gtk.HBox):
    """
    Row of buttons used to navigate and add keyframes and frame 
    entry box for active keyframe. Parent editor must implemnt interface
    defined by connect methods:
        editor_parent.add_pressed()
        editor_parent.delete_pressed()
        editor_parent.prev_pressed()
        editor_parent.next_pressed()
        editor_parent.prev_frame_pressed()
        editor_parent.next_frame_pressed()
    """
    def __init__(self, editor_parent):
        gtk.HBox.__init__(self, False, 2)
        
        # Buttons
        self.add_button = guiutils.get_image_button("add_kf.png", BUTTON_WIDTH, BUTTON_HEIGHT)
        self.delete_button = guiutils.get_image_button("delete_kf.png", BUTTON_WIDTH, BUTTON_HEIGHT)
        self.prev_kf_button = guiutils.get_image_button("prev_kf.png", BUTTON_WIDTH, BUTTON_HEIGHT)
        self.next_kf_button = guiutils.get_image_button("next_kf.png", BUTTON_WIDTH, BUTTON_HEIGHT)
        self.prev_frame_button = guiutils.get_image_button("kf_edit_prev_frame.png", BUTTON_WIDTH, BUTTON_HEIGHT)
        self.next_frame_button = guiutils.get_image_button("kf_edit_next_frame.png", BUTTON_WIDTH, BUTTON_HEIGHT)
        self.add_button.connect("clicked", lambda w,e: editor_parent.add_pressed(), None)
        self.delete_button.connect("clicked", lambda w,e: editor_parent.delete_pressed(), None)
        self.prev_kf_button.connect("clicked", lambda w,e: editor_parent.prev_pressed(), None)
        self.next_kf_button.connect("clicked", lambda w,e: editor_parent.next_pressed(), None)
        self.prev_frame_button.connect("clicked", lambda w,e: editor_parent.prev_frame_pressed(), None)
        self.next_frame_button.connect("clicked", lambda w,e: editor_parent.next_frame_pressed(), None)
        
        # Position entry
        self.kf_pos_label = gtk.Label()
        self.modify_font(pango.FontDescription("light 8"))
        self.kf_pos_label.set_text("0")
        
        # Build row
        self.pack_start(self.add_button, False, False, 0)
        self.pack_start(self.delete_button, False, False, 0)
        self.pack_start(self.prev_kf_button, False, False, 0)
        self.pack_start(self.next_kf_button, False, False, 0)
        self.pack_start(self.prev_frame_button, False, False, 0)
        self.pack_start(self.next_frame_button, False, False, 0)
        self.pack_start(gtk.Label(), True, True, 0)
        self.pack_start(self.kf_pos_label, False, False, 0)
        self.pack_start(guiutils.get_pad_label(1, 10), False, False, 0)

    def set_frame(self, frame):
        frame_str = utils.get_tc_string(frame)
        self.kf_pos_label.set_text(frame_str)
        

class GeometryEditorButtonsRow(gtk.HBox):
    def __init__(self, editor_parent):
        """
        editor_parent needs to implement interface:
        -------------------------------------------
        editor_parent.view_size_changed(widget_active_index)
        editor_parent.reset_rect_pressed()
        editor_parent.reset_rect_ratio_pressed()
        """
        gtk.HBox.__init__(self, False, 2)  
        name_label = gtk.Label(_("View:"))

        self.reset_b = gtk.Button(_("Reset"))
        self.ratio_b = gtk.Button(_("Ratio"))
        self.reset_b.set_tooltip_text(_("Reset source image to original position and size"))
        self.ratio_b.set_tooltip_text(_("Set source image to original aspect ratio."))
        self.reset_b.connect("clicked", lambda w,e: editor_parent.reset_rect_pressed(), 
                             None)
        self.ratio_b.connect("clicked", lambda w,e: editor_parent.reset_rect_ratio_pressed(), 
                             None)

        size_select = gtk.combo_box_new_text()
        size_select.append_text(_("Large"))
        size_select.append_text(_("Medium"))
        size_select.append_text(_("Small"))
        size_select.set_active(1)
        size_select.set_size_request(120, 30)
        font_desc = pango.FontDescription("normal 9")
        size_select.child.modify_font(font_desc)
        size_select.connect("changed", lambda w,e: editor_parent.view_size_changed(w.get_active()), 
                            None)
        # Build row
        self.pack_start(guiutils.get_pad_label(2, 10), False, False, 0)
        self.pack_start(name_label, False, False, 0)
        self.pack_start(size_select, False, False, 0)
        self.pack_start(gtk.Label(), True, True, 0)
        self.pack_start(self.reset_b, False, False, 0)
        self.pack_start(self.ratio_b, False, False, 0)
        self.pack_start(guiutils.get_pad_label(2, 10), False, False, 0)


class AbstractKeyFrameEditor(gtk.VBox):
    """
    Extending editor is parent editor for ClipKeyFrameEditor and is updated
    from timeline posion changes.
    
    Extending editor also has slider for setting keyframe values.
    """
    def __init__(self, editable_property, use_clip_in=True):
        # editable_property is KeyFrameProperty
        gtk.VBox.__init__(self, False, 2)
        self.editable_property = editable_property
        self.clip_tline_pos = editable_property.get_clip_tline_pos()

        self.clip_editor = ClipKeyFrameEditor(editable_property, self, use_clip_in)

        # Some filters start keyframes from *MEDIA* frame 0
        # Some filters or compositors start keyframes from *CLIP* frame 0
        # Filters starting from *media* 0 need offset to clip start added to all values
        self.use_clip_in = use_clip_in
        if self.use_clip_in == True:
            self.clip_in = editable_property.clip.clip_in
        else:
            self.clip_in = 0

        # Value slider
        row, slider = guiutils.get_slider_row(editable_property, self.slider_value_changed)
        self.value_slider_row = row
        self.slider = slider

    def display_tline_frame(self, tline_frame):
        # This is called after timeline current frame changed. 
        # If timeline pos changed because drag is happening _here_,
        # updating once more is wrong
        if self.clip_editor.drag_on == True:
            return
        
        # update clipeditor pos
        clip_frame = tline_frame - self.clip_tline_pos + self.clip_in
        self.clip_editor.set_and_display_clip_frame(clip_frame)
        self.update_editor_view(False)
    
    def update_clip_pos(self):
        # This is called after position of clip has been edited.
        # We'll need to update some values to get keyframes on correct positions again
        self.editable_property.update_clip_index()
        self.clip_tline_pos = self.editable_property.get_clip_tline_pos()
        if self.use_clip_in == True:
            self.clip_in = self.editable_property.clip.clip_in
        else:
            self.clip_in = 0
        self.clip_editor.clip_in = self.editable_property.clip.clip_in

    def update_slider_value_display(self, frame):
        # This is called after frame changed or mouse release to update
        # slider value without causing 'changed' signal to update keyframes.
        if self.editable_property.value_changed_ID != DISCONNECTED_SIGNAL_HANDLER:
            self.slider.get_adjustment().handler_block(self.editable_property.value_changed_ID)

        new_value = _get_frame_value(frame, self.clip_editor.keyframes)
        self.editable_property.adjustment.set_value(new_value)
        if self.editable_property.value_changed_ID != DISCONNECTED_SIGNAL_HANDLER:
            self.slider.get_adjustment().handler_unblock(self.editable_property.value_changed_ID) 

    def seek_tline_frame(self, clip_frame):
        PLAYER().seek_frame(self.clip_tline_pos + clip_frame - self.clip_in)
    
    def update_editor_view(self, seek_tline=True):
        print "update_editor_view not implemented"
        
class KeyFrameEditor(AbstractKeyFrameEditor):
    """
    Class combines named value slider with ClipKeyFrameEditor and 
    control buttons to create keyframe editor for a single keyframed
    numerical value property. 
    """
    def __init__(self, editable_property, use_clip_in=True):
        AbstractKeyFrameEditor.__init__(self, editable_property, use_clip_in)

        # default parser
        self.clip_editor.keyframe_parser = propertyparse.single_value_keyframes_string_to_kf_array

        # parsers for other editable_property types
        if isinstance(editable_property, propertyedit.OpacityInGeomKeyframeProperty):
            self.clip_editor.keyframe_parser = propertyparse.geom_keyframes_value_string_to_opacity_kf_array
            
        editable_property.value.strip('"')
        self.clip_editor.set_keyframes(editable_property.value, editable_property.get_in_value)
        
        self.buttons_row = ClipEditorButtonsRow(self)
        
        self.pack_start(self.value_slider_row, False, False, 0)
        self.pack_start(self.clip_editor.widget, False, False, 0)
        self.pack_start(self.buttons_row, False, False, 0)

        self.active_keyframe_changed() # to do update gui to current values

    def slider_value_changed(self, adjustment):
        value = adjustment.get_value()        
        # Add key frame if were not on active key frame
        active_kf_frame = self.clip_editor.get_active_kf_frame()
        current_frame = self.clip_editor.current_clip_frame
        if current_frame != active_kf_frame:
            self.clip_editor.add_keyframe(current_frame)
            self.clip_editor.set_active_kf_value(value)
            self.update_editor_view()
            self.update_property_value()
        else: # if on kf, just update value
            self.clip_editor.set_active_kf_value(value)
            self.update_property_value()

    def active_keyframe_changed(self):
        frame = self.clip_editor.current_clip_frame
        keyframes = self.clip_editor.keyframes
        value = _get_frame_value(frame, keyframes)
        self.slider.set_value(value)
        self.buttons_row.set_frame(frame)
        self.seek_tline_frame(frame)
        
    def clip_editor_frame_changed(self, clip_frame):
        self.seek_tline_frame(clip_frame)
        self.buttons_row.set_frame(clip_frame)

    def add_pressed(self):
        self.clip_editor.add_keyframe(self.clip_editor.current_clip_frame)
        self.update_editor_view()
        self.update_property_value()

    def delete_pressed(self):
        self.clip_editor.delete_active_keyframe()
        self.update_editor_view()
        self.update_property_value()

    def next_pressed(self):
        self.clip_editor.set_next_active()
        self.update_editor_view()
    
    def prev_pressed(self):
        self.clip_editor.set_prev_active()
        self.update_editor_view()
    
    def prev_frame_pressed(self):
        self.clip_editor.move_clip_frame(-1)
        self.update_editor_view()

    def next_frame_pressed(self):
        self.clip_editor.move_clip_frame(1)
        self.update_editor_view()
    
    def pos_entry_enter_hit(self, entry):
        val = entry.get_text() #error handl?
        self.clip_editor.active_kf_pos_entered(int(val))
        self.update_editor_view()
        self.update_property_value()
    
    def keyframe_dragged(self, active_kf, frame):
        pass

    def update_editor_view(self, seek_tline=True):
        frame = self.clip_editor.current_clip_frame
        keyframes = self.clip_editor.keyframes
        value = _get_frame_value(frame, keyframes)
        self.buttons_row.set_frame(frame)
        if seek_tline == True:
            self.seek_tline_frame(frame)
        self.queue_draw()

    def connect_to_update_on_release(self):
        self.editable_property.adjustment.disconnect(self.editable_property.value_changed_ID)
        self.editable_property.value_changed_ID = DISCONNECTED_SIGNAL_HANDLER
        self.slider.connect("button-release-event", lambda w, e:self.slider_value_changed(w.get_adjustment()))
        
    def update_property_value(self):
        self.editable_property.write_out_keyframes(self.clip_editor.keyframes)


class GeometryEditor(AbstractKeyFrameEditor):
    """
    GUI component that edits position, scale and opacity of a MLT property.
    """
    def __init__(self, editable_property, use_clip_in=True):
        AbstractKeyFrameEditor.__init__(self, editable_property, use_clip_in)
        
        # Create components
        self.geom_buttons_row = GeometryEditorButtonsRow(self)

        self.geom_kf_edit = GeometryKeyFrameEditor(editable_property, self)
        self.geom_kf_edit.init_editor(current_sequence().profile.width(),
                                      current_sequence().profile.height(),
                                      GEOM_EDITOR_SIZE_MEDIUM)
        editable_property.value.strip('"')
        self.geom_kf_edit.keyframe_parser = propertyparse.geom_keyframes_value_string_to_geom_kf_array
        self.geom_kf_edit.set_keyframes(editable_property.value, editable_property.get_in_value)
        
        g_frame = gtk.Frame()
        g_frame.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        g_frame.add(self.geom_kf_edit.widget)
             
        self.buttons_row = ClipEditorButtonsRow(self)
        
        # Create clip editor keyframes from geom editor keyframes
        # that contain the property values when opening editor.
        # From now on clip editor opacity values are used until editor is discarded.
        keyframes = []
        for kf in self.geom_kf_edit.keyframes:
            frame, rect, opacity = kf
            clip_kf = (frame, opacity)
            keyframes.append(clip_kf)
        self.clip_editor.keyframes = keyframes
      
        # Build gui
        self.pack_start(self.geom_buttons_row, False, False, 0)
        self.pack_start(g_frame, False, False, 0)
        self.pack_start(self.value_slider_row, False, False, 0)
        self.pack_start(self.clip_editor.widget, False, False, 0)
        self.pack_start(self.buttons_row, False, False, 0)

        self.active_keyframe_changed() # to do update gui to current values

        self.queue_draw()

    def add_pressed(self):
        self.clip_editor.add_keyframe(self.clip_editor.current_clip_frame)
        self.geom_kf_edit.add_keyframe(self.clip_editor.current_clip_frame)

        frame = self.clip_editor.get_active_kf_frame()
        self.update_editor_view_with_frame(frame)
        self.update_property_value()

    def delete_pressed(self):
        active = self.clip_editor.active_kf_index
        self.clip_editor.delete_active_keyframe()
        self.geom_kf_edit.delete_active_keyframe(active)
        
        frame = self.clip_editor.get_active_kf_frame()
        self.update_editor_view_with_frame(frame)
        self.update_property_value()
        
    def next_pressed(self):
        self.clip_editor.set_next_active()
        frame = self.clip_editor.get_active_kf_frame()
        self.update_editor_view_with_frame(frame)
    
    def prev_pressed(self):
        self.clip_editor.set_prev_active()
        frame = self.clip_editor.get_active_kf_frame()
        self.update_editor_view_with_frame(frame)
    
    def slider_value_changed(self, adjustment):
        value = adjustment.get_value()
        self.clip_editor.set_active_kf_value(value)
        self.update_property_value()
    
    def view_size_changed(self, selected_index):
        y_fract = GEOM_EDITOR_SIZES[selected_index]
        self.geom_kf_edit.set_view_size(y_fract)
        self.update_editor_view_with_frame(self.clip_editor.current_clip_frame)
        
    def clip_editor_frame_changed(self, frame):
        self.update_editor_view_with_frame(frame)

    def prev_frame_pressed(self):
        self.clip_editor.move_clip_frame(-1)
        self.update_editor_view(True)

    def next_frame_pressed(self):
        self.clip_editor.move_clip_frame(1)
        self.update_editor_view(True)

    def geometry_edit_started(self): # callback from geom_kf_edit
        self.clip_editor.add_keyframe(self.clip_editor.current_clip_frame)
        self.geom_kf_edit.add_keyframe(self.clip_editor.current_clip_frame)
        
    def geometry_edit_finished(self): # callback from geom_kf_edit
        self.geom_kf_edit.set_keyframe_to_edit_rect(self.clip_editor.active_kf_index)
        self.update_editor_view_with_frame(self.clip_editor.current_clip_frame)
        self.update_property_value()
        
    def update_request_from_geom_editor(self): # callback from geom_kf_edit
        self.update_editor_view_with_frame(self.clip_editor.current_clip_frame)

    def keyframe_dragged(self, active_kf, frame):
        self.geom_kf_edit.set_keyframe_frame(active_kf, frame)
        
    def active_keyframe_changed(self): # callback from clip_editor
        kf_frame = self.clip_editor.get_active_kf_frame()
        self.update_editor_view_with_frame(kf_frame)

    def reset_rect_pressed(self):
        self.geom_kf_edit.reset_active_keyframe_rect(self.clip_editor.active_kf_index)
        frame = self.clip_editor.get_active_kf_frame()
        self.update_editor_view_with_frame(frame)
        self.update_property_value()

    def reset_rect_ratio_pressed(self):
        self.geom_kf_edit.reset_active_keyframe_rect_ratio(self.clip_editor.active_kf_index)
        frame = self.clip_editor.get_active_kf_frame()
        self.update_editor_view_with_frame(frame)
        self.update_property_value()

    def update_editor_view(self, seek_tline_frame=False):
        # This gets called when tline frame is changed from outside
        # Call update_editor_view_with_frame that is used when udating from inside the object.
        # seek_tline_frame will be False to stop endless loop of updates
        frame = self.clip_editor.current_clip_frame
        self.update_editor_view_with_frame(frame, seek_tline_frame)

    def update_editor_view_with_frame(self, frame, seek_tline_frame=True):
        self.update_slider_value_display(frame)
        self.geom_kf_edit.set_clip_frame(frame)
        self.buttons_row.set_frame(frame)
        if seek_tline_frame == True:
            self.seek_tline_frame(frame)
        self.queue_draw()

    def seek_tline_frame(self, clip_frame):
        PLAYER().seek_frame(self.clip_tline_pos + clip_frame)

    def update_property_value(self):
        write_keyframes = []
        for opa_kf, geom_kf in zip(self.clip_editor.keyframes, self.geom_kf_edit.keyframes):
            frame, opacity = opa_kf
            frame, rect, rubbish_opacity = geom_kf # rubbish_opacity was just doing same thing twice for nothing,
                                                   # and can be removed to clean up code, but could not bothered right now
            write_keyframes.append((frame, rect, opacity))
        
        self.editable_property.write_out_keyframes(write_keyframes)

def _get_frame_value(frame, keyframes):
    for i in range(0, len(keyframes)):
        kf_frame, kf_value = keyframes[i]
        if kf_frame == frame:
            return kf_value
        
        try:
            # See if frame between this and next keyframe
            frame_n, value_n = keyframes[i + 1]
            if ((kf_frame < frame)
                and (frame < frame_n)):
                time_fract = float((frame - kf_frame)) / float((frame_n - kf_frame))
                value_range = value_n - kf_value
                return kf_value + time_fract * value_range
        except: # past last frame, use its value
            return kf_value
   
