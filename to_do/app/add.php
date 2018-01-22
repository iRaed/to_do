<?php 
require "config.php";
function validate_date($date_string){
    if ($time = strtotime($date_string)) {
        return $time;
    } else {
        return false;
    }
    
}
if ($_SERVER['REQUEST_METHOD'] == 'POST'){
    //اختبار عدم فراغ حقلي وصف المهمة والتاريخ
    if ((!empty($_POST['task_name'])) and (!empty($_POST['due_date']))){
        //أختبار صحة التاريخ المدخل
        if ($due_date = validate_date($_POST['due_date'])) {
           //تخزين المهمة داخل قاعدة البيانات
           $description = $_POST['task_name'];
           $due_date = date('Y-m-d H:i:s', $due_date);
           $connection->query("INSERT INTO tasks (description, due_date, user_id)
           VALUES ('".$description."', '".$due_date."', '".$_SESSION['user_id']."')");
        } 
         //التاريخ المدخل غير صحيح 
        else {
            // إرسال رسالة خطأ إلى المستخدم تطلب منه إعادة إدخال التاريخ بصورة صحيحة
            $errors['not_valid_date'] = 'يجب أن تدخل التاريخ بصورة صحيحة ، مثل: 1-1-2014 ';
            $_SESSION['errors'] = $errors;
        }
           
    }
    //أحد الحقلين أو كليهما فارغين
    else{
        //إرسال رسالة خطأ إلى المستخدم
        if (empty($_POST['task_name'])) {
            $errors['required_name'] = 'يجب أن تقوم بكتابة وصف للمهمة';
        }
        if (empty($_POST['due_date'])) {
            $errors['require_date'] = 'يحب أن تقوم بتعيين آخر مهملة لإنجاز المهمة';
        }
        $_SESSION['errors'] = $errors;
    }
    header('Location: ../index.php');
}