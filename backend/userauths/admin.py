# 1.2 task 2 registering user and profile


from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from userauths.models import User, Profile

class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('email', 'username')

class CustomUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profile'
    fk_name = 'user'

class CustomUserAdmin(BaseUserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    
    list_display = ('email', 'username', 'full_name', 'phone', 'is_staff')
    list_filter = ('is_staff', 'is_superuser', 'is_active')
    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Personal info', {'fields': ('full_name', 'phone')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2', 'full_name', 'phone'),
        }),
    )
    search_fields = ('email', 'username', 'full_name')
    ordering = ('email',)
    inlines = (ProfileInline,)

class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'gender')
    search_fields = ('user__email', 'user__username', 'full_name')
    raw_id_fields = ('user',)

# First register the User model with your custom admin
admin.site.register(User, CustomUserAdmin)

# Then register the Profile model
admin.site.register(Profile, ProfileAdmin)