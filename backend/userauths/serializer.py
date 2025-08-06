from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers 
from userauths.models import User, Profile
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class MyTokenObtainPairSerializer(TokenObtainPairSerializer):   # Creates our custom token class that inherits from the basic one


    @classmethod
    def get_token(cls, user):

        # Defines a class method that will generate our token

#cls refers to the class itself

#user is the user who is logging in

        token= super().get_token(user)  #Gets the basic token from the parent class (with standard fields like user ID)


# This will Adds extra information to the token:
        token['full_name']= user.full_name
        token['email'] = user.email
        token['username']= user.username

        try:  #Tries to add vendor ID if the user is a vendor


            token['vendor_id'] = user.vendor.id

        except:
            token['vendor_id'] = 0  #If they're not a vendor (which would cause an error), sets vendor_id to 0 instead


        return token  #Returns the complete token with all our custom information
# class RegistrationSerializer(serializers.ModelSerializer):
#     password = serializers.CharField(write_only = True,validators=[validate_password], required= True)
#     confirm_password = serializers.CharField(write_only = True, required= True)

#     class Meta:
#         model = User
#         fields = ['full_name','phone','username','email', 'password', 'confirm_password']

#     def validate(self, attrs):
#         if attrs["password"] != attrs["confirm_password"]:
#             raise serializers.ValidationError({"Password": "Password does not match"})
#         return attrs

class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password], required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ['full_name', 'username', 'email', 'phone', 'password', 'confirm_password']  # Make sure 'phone' is in fields

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:  # Fixed comparison
            raise serializers.ValidationError({"Password": "Password does not match"})
        return attrs
    
    def create(self, validated_data):
        user = User.objects.create(
            full_name=validated_data['full_name'],
            username=validated_data['username'],
            email=validated_data['email'],
            phone=validated_data.get('phone', '')  # Using get() in case phone is optional
        )
        
        user.set_password(validated_data['password'])  # Fixed: Using validated_data instead of validate_password
        user.save()
        return user
    
    def create(self, validated_data):
        user = User.objects.create(
            full_name = validated_data['full_name'],
            phone = validated_data['phone'],
            email = validated_data['email'],)
        
        email_user, mobile = user.email.split("@")    
        user.set_password(validated_data['password'])
        user.save()
        return user




class UserSerializer(serializers.ModelSerializer):
    class Meta:
        # When specifying fields or exclude in the Meta class, you must use square brackets because DRF expects a list of field names
        model = User
        fieds = ['__all__']   # you can add the field you want to add like full_name, email and so on but with this i want to make use of all field in the User modelalready created

    # if you don't ant to include some field u can use exclude
   #exclude = ['full_name']

#    serializing the profile 

class ProfileSterilizer(serializers.ModelSerializer):
    # user = UserSerializer()
    class Meta:
        model = Profile
        fields = ['__all__']

    def to_representation(self,instance):  # takes the two arguments that's instance and self 
        # the self argument reps the current instance of the class i created (profile class)
        #  instance argument represent the object being sterialized (profile object)
        # convert instance object into dictionary
#defining a method within a class
        response = super().to_representation(instance)   #Purpose: Calls the parent class's to_representation() method to get the default serialized data (as a Python dictionary) for the instance.
        response['user'] = UserSerializer(instance.user).data  # Purpose: Adds a nested user field to the serialized data by:


        return response
    # Returns the modified dictionary (now including the nested user data) as the final serialized output.